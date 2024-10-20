import os
import fcntl
import re
import tempfile
import threading
import time
import wave
import logging
from logging.handlers import RotatingFileHandler
import subprocess
import sys
import ffmpeg
import pyaudio
import pyperclip
import requests
from pynput import keyboard
from groq import Groq
from deepgram import (
    DeepgramClient,
    PrerecordedOptions,
    FileSource,
)


# Set up logging
log_file = 'voiceflow.log'
log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
log_handler = RotatingFileHandler(log_file, maxBytes=1024*1024, backupCount=5)
log_handler.setFormatter(log_formatter)

logger = logging.getLogger('voiceflow')
logger.setLevel(logging.DEBUG)
logger.addHandler(log_handler)

# Add a stream handler for console output when not running in the background
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
logger.addHandler(console_handler)

# Constants
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100
MAX_RECORD_SECONDS = 300  # 5 minutes
WAVE_OUTPUT_FILENAME = "output.wav"
PROCESSED_OUTPUT_FILENAME = "processed_output.wav"

# API Keys (loaded from environment variables)
GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '')
DEEPGRAM_API_KEY = os.environ.get('DEEPGRAM_API_KEY', '')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')

# Debug logging for API keys
logger.debug(f"GROQ_API_KEY: {'set' if GROQ_API_KEY else 'not set'}")
logger.debug(f"DEEPGRAM_API_KEY: {'set' if DEEPGRAM_API_KEY else 'not set'}")
logger.debug(f"OPENAI_API_KEY: {'set' if OPENAI_API_KEY else 'not set'}")

# Global variables
is_recording = False
p = pyaudio.PyAudio()
frames = []
alt_pressed = False


def on_press(key):
    global is_recording, frames, alt_pressed
    try:
        if key == keyboard.Key.alt:
            alt_pressed = True
        elif key.char == 't' and alt_pressed and not is_recording:
            is_recording = True
            frames = []
            threading.Thread(target=record_audio).start()
            logger.info("Recording started")
    except AttributeError:
        pass


def on_release(key):
    global is_recording, alt_pressed
    try:
        if key == keyboard.Key.alt:
            alt_pressed = False
        if (key == keyboard.Key.alt or key.char == 't') and is_recording:
            is_recording = False
            logger.info("Recording stopped")
            process_audio()
    except AttributeError:
        pass


def record_audio():
    global is_recording, frames
    try:
        stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE,
                        input=True, frames_per_buffer=CHUNK)
        logger.info("Recording started")

        start_time = time.time()
        while is_recording and (time.time() - start_time) < MAX_RECORD_SECONDS:
            data = stream.read(CHUNK)
            frames.append(data)
            if (time.time() - start_time) % 1 < 0.1:  # Log every second
                logger.info(f"Recording in progress: {
                            time.time() - start_time:.1f} seconds")

        logger.info(f"Recording finished. Duration: {
                    time.time() - start_time:.1f} seconds. Number of frames: {len(frames)}")
        stream.stop_stream()
        stream.close()
    except Exception as e:
        logger.error(f"Error during audio recording: {e}")
        is_recording = False


def process_audio():
    global frames
    logger.info("Starting audio processing")

    try:
        # Save the recorded audio to a temporary file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
            temp_file_name = temp_file.name
            logger.info(f"Temporary file created: {temp_file_name}")

            wf = wave.open(temp_file_name, 'wb')
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(p.get_sample_size(FORMAT))
            wf.setframerate(RATE)
            wf.writeframes(b''.join(frames))
            wf.close()

            file_size = os.path.getsize(temp_file_name)
            logger.info(f"Audio data written to temporary file. File size: {
                        file_size} bytes")

        # Check if the recording is at least 1 second long
        if len(frames) < RATE / CHUNK:
            logger.info(
                "Recording too short (less than 1 second). Discarding.")
            return

        logger.info(f"Recording length: {
                    len(frames) * CHUNK / RATE:.2f} seconds")

        # Preprocess audio (downsample to 16kHz)
        try:
            logger.info(f"Starting audio preprocessing with ffmpeg")
            stream = ffmpeg.input(temp_file_name)
            stream = ffmpeg.output(
                stream, PROCESSED_OUTPUT_FILENAME, ar=16000, ac=1, acodec='pcm_s16le')
            ffmpeg.run(stream, capture_stdout=True, capture_stderr=True)
            logger.info(f"Audio preprocessing completed. Output file: {
                        PROCESSED_OUTPUT_FILENAME}")
        except ffmpeg.Error as e:
            logger.error(f"Error during audio preprocessing: {
                         e.stderr.decode()}")
            raise

        # Transcribe audio
        transcription = transcribe_audio(PROCESSED_OUTPUT_FILENAME)
        if not transcription:
            logger.error("Transcription failed")
            raise Exception("Transcription failed")

        logger.info(f"Transcription result: {transcription}")
        print(f"Transcription: {transcription}")  # Console output

        # Process transcription with AI
        processed_text = process_transcription(transcription)

        # Output processed text
        pyperclip.copy(processed_text)
        insert_text_into_active_window(processed_text)
        logger.info("Text copied to clipboard and inserted into active window")

    except Exception as e:
        logger.error(f"Error during audio processing: {e}")
    finally:
        # Clean up temporary files
        try:
            os.unlink(temp_file_name)
            os.unlink(PROCESSED_OUTPUT_FILENAME)
            logger.info("Temporary files cleaned up")
        except Exception as e:
            logger.error(f"Error cleaning up temporary files: {e}")


def transcribe_audio(audio_file):
    """
    Transcribe the audio file using Groq API or Deepgram API as fallback.

    Returns the transcribed text or None if both APIs fail.
    """
    if not os.path.exists(audio_file):
        logger.error(f"Audio file does not exist: {audio_file}")
        return None

    # Verify file format
    try:
        with wave.open(audio_file, 'rb') as wav_file:
            logger.info(f"Audio file details: channels={wav_file.getnchannels()}, width={
                        wav_file.getsampwidth()}, rate={wav_file.getframerate()}, frames={wav_file.getnframes()}")
    except wave.Error as e:
        logger.error(f"Invalid WAV file: {e}")
        return None

    # Try Groq API first
    try:
        file_size = os.path.getsize(audio_file)
        if file_size == 0:
            logger.error("Audio file is empty")
            return None

        client = Groq(api_key=os.environ.get('GROQ_API_KEY'))
        with open(audio_file, "rb") as file:
            transcription = client.audio.transcriptions.create(
                file=(os.path.basename(audio_file), file.read(), 'audio/wav'),
                model="whisper-large-v3-turbo",
                response_format="text",
                language="en"
            )
        return transcription
    except Exception as e:
        logger.error(f"Groq API error: {e}")

    # Fallback to Deepgram API
    try:
        deepgram = DeepgramClient(os.environ.get('DEEPGRAM_API_KEY'))

        with open(audio_file, "rb") as file:
            buffer_data = file.read()

        payload: FileSource = {
            "buffer": buffer_data,
        }

        options = PrerecordedOptions(
            model="nova-2",
            smart_format=True,
            utterances=True,
            punctuate=True,
            diarize=True,
        )

        response = deepgram.listen.prerecorded.v(
            "1").transcribe_file(payload, options)

        # Extract the transcript from the response
        transcript = response["results"]["channels"][0]["alternatives"][0]["transcript"]
        return transcript

    except Exception as e:
        logger.error(f"Deepgram API error: {e}")

    return None


def process_transcription(transcription):
    """
    Process the transcription using Groq API or OpenAI API as fallback.

    Returns the processed text or None if both APIs fail.
    """
    prompt = f"For the given transcription with unclear and incorrect grammar, spelling and capitalization, return a cleaned text that is the exact representation of the transcript but in a written form with correct grammar, spelling, capitalization, etc. Do not add any additional text or comments. Do not give me multiple options. ONLY output the cleaned text. <TRANSCRIPT>{
        transcription}</TRANSCRIPT>"

    logger.info(f"Prompt for LLM: {prompt}")
    print(f"Prompt for LLM: {prompt}")  # Console output

    # Try Groq API first
    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json={
                "model": "llama-3.1-8b-instant",
                "messages": [
                    {"role": "system", "content": "You are a helpful assistant that improves transcriptions."},
                    {"role": "user", "content": prompt}
                ]
            },
            timeout=30
        )
        response.raise_for_status()
        processed_text = response.json()['choices'][0]['message']['content']
    except requests.RequestException as e:
        logger.error("Groq API error: %s", e)
        # Fallback to OpenAI API
        try:
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                json={
                    "model": "gpt-4",
                    "messages": [
                        {"role": "system", "content": "You are a helpful assistant that improves transcriptions."},
                        {"role": "user", "content": prompt}
                    ]
                },
                timeout=30
            )
            response.raise_for_status()
            processed_text = response.json(
            )['choices'][0]['message']['content']
        except requests.RequestException as e:
            logger.error("OpenAI API error: %s", e)
            return None

    logger.info(f"Raw LLM output: {processed_text}")
    print(f"Raw LLM output: {processed_text}")  # Console output

    # Check if the processed text has more than one sentence
    sentences = re.split(r'(?<=[.!?])\s+', processed_text.strip())
    if len(sentences) > 1:
        processed_text += '\n'  # Add an extra newline if there's more than one sentence

    logger.info(f"Final processed text: {processed_text}")
    print(f"Final processed text: {processed_text}")  # Console output

    return processed_text


# def create_image():
#     """Create a simple image for the tray icon."""
#     width = 64
#     height = 64
#     color1 = (255, 0, 0)  # Red
#     color2 = (0, 255, 0)  # Green
#     image = Image.new('RGB', (width, height), color1)
#     pixels = image.load()
#     for i in range(width):
#         for j in range(height):
#             if (i + j) % 2 == 0:
#                 pixels[i, j] = color2
#     return image


# def update_icon(status):
#     """Update the tray icon with the current status."""
#     global tray_icon
#     if tray_icon:
#         tray_icon.icon = create_image()
#         tray_icon.title = f"VoiceFlow: {status}"


# def setup_tray_icon():
#     """Set up the tray icon with a menu."""
#     global tray_icon
#     try:
#         tray_icon = icon('VoiceFlow', create_image(), menu=menu(
#             item('Quit', quit_app)
#         ))
#         tray_icon.run()
#     except Exception as e:
#         logger.warning(f"Failed to create tray icon: {e}")
#         logger.info("Tray icon not available. Use Ctrl+C to quit.")
#         # Implement a fallback method to keep the script running
#         try:
#             while True:
#                 time.sleep(1)
#         except KeyboardInterrupt:
#             logger.info("Exiting...")
#             quit_app()


def quit_app():
    """Quit the application."""
    logger.info("Application shutting down")
    # if tray_icon:
    #     tray_icon.stop()
    os._exit(0)


def insert_text_into_active_window(text):
    """Insert the processed text into the active window using xclip and xdotool."""
    try:
        logger.info(f"Attempting to paste text: {text}")
        # Copy the text to clipboard
        subprocess.run(['xclip', '-selection', 'clipboard'],
                       input=text.encode('utf-8'), check=True)

        # Simulate Ctrl+V to paste
        subprocess.run(
            ['xdotool', 'key', '--clearmodifiers', 'ctrl+v'], check=True)

        logger.info("Text pasted into active window successfully")
    except subprocess.CalledProcessError as e:
        logger.error("Failed to paste text into active window: %s", e)
    except FileNotFoundError:
        logger.error(
            "xclip or xdotool not found. Please install them using: sudo apt-get install xclip xdotool")


def check_permissions():
    """Check if the script has the necessary permissions."""
    try:
        # Check microphone access
        p = pyaudio.PyAudio()
        stream = p.open(format=FORMAT, channels=CHANNELS,
                        rate=RATE, input=True, frames_per_buffer=CHUNK)
        stream.stop_stream()
        stream.close()
        p.terminate()

        # Check file writing
        with tempfile.NamedTemporaryFile(mode='w', delete=True) as temp_file:
            temp_file.write('Test')

        logger.info("Permissions check passed")
        return True
    except (OSError, IOError) as e:
        logger.error("Permissions check failed: %s", e)
        return False


# def check_tray_support():
#     """Check if the system supports tray icons."""
#     try:
#         # test_icon = icon('test', Image.new('RGB', (64, 64), color='red'))
#         # test_icon.visible = False
#         return True
#     except (ImportError, RuntimeError) as e:
#         logger.error("Tray icon not supported: %s", e)
#         return False


def obtain_lock():
    lock_file = open("/tmp/voiceflow.lock", "w")
    try:
        fcntl.lockf(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        print("Another instance is already running. Exiting.")
        sys.exit(1)
    return lock_file


if __name__ == "__main__":
    lock = obtain_lock()
    logger.info("Starting VoiceFlow")
    if not check_permissions():
        logger.error(
            "Error: Insufficient permissions. Please check the log file for details.")
        sys.exit(1)

    if not all([GROQ_API_KEY, DEEPGRAM_API_KEY, OPENAI_API_KEY]):
        logger.error(
            "One or more required API keys are missing. Please set all required environment variables.")
        sys.exit(1)

    # Set up the keyboard listener
    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()
    logger.info(
        "Keyboard listener started. Press Alt+T to start/stop recording.")

    try:
        # Keep the script running
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received. Exiting...")
    finally:
        listener.stop()
        logger.info("Keyboard listener stopped.")
