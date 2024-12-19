# Standard library imports
import fcntl
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import wave
from logging.handlers import RotatingFileHandler

# Third-party imports
import ffmpeg
import pyaudio
import pyperclip
import requests
from groq import Groq
from pynput import keyboard

# Set up logging first
log_file = "voiceflow.log"
log_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
log_handler = RotatingFileHandler(log_file, maxBytes=1024 * 1024, backupCount=5)
log_handler.setFormatter(log_formatter)

logger = logging.getLogger("voiceflow")
logger.setLevel(logging.DEBUG)
logger.addHandler(log_handler)

# Add a stream handler for console output when not running in the background
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
logger.addHandler(console_handler)

try:
    from dotenv import load_dotenv
except ImportError:
    logger.error("Error: python-dotenv package is not installed. Please run: uv pip sync requirements.txt")
    sys.exit(1)

# Load environment variables from .env file
try:
    load_dotenv()
    logger.debug("Successfully loaded .env file")
except Exception as e:
    logger.error(f"Error loading .env file: {e}")
    sys.exit(1)

# Constants
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100
MAX_RECORD_SECONDS = 300  # 5 minutes
WAVE_OUTPUT_FILENAME = "output.wav"
PROCESSED_OUTPUT_FILENAME = "processed_output.wav"

# API Keys and endpoints (loaded from environment variables)
FIREWORKS_API_KEY = os.environ.get("FIREWORKS_API_KEY", "")
CEREBRAS_API_KEY = os.environ.get("CEREBRAS_API_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")  # Fallback
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")  # Fallback

FIREWORKS_ENDPOINT = "https://audio-prod.us-virginia-1.direct.fireworks.ai/v1/audio/transcriptions"
CEREBRAS_ENDPOINT = "https://api.cerebras.ai/v1/chat/completions"

# Debug logging for API keys
logger.debug(f"FIREWORKS_API_KEY: {'set' if FIREWORKS_API_KEY else 'not set'}")
logger.debug(f"CEREBRAS_API_KEY: {'set' if CEREBRAS_API_KEY else 'not set'}")
logger.debug(
    f"GROQ_API_KEY: {'set' if GROQ_API_KEY else 'not set'} (length: {len(GROQ_API_KEY) if GROQ_API_KEY else 0})"
)
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
        elif key.char == "t" and alt_pressed and not is_recording:
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
        if (key == keyboard.Key.alt or key.char == "t") and is_recording:
            is_recording = False
            logger.info("Recording stopped")
            process_audio()
    except AttributeError:
        pass


def record_audio():
    global is_recording, frames
    try:
        stream = p.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            frames_per_buffer=CHUNK,
        )
        logger.info("Recording started")

        start_time = time.time()
        while is_recording and (time.time() - start_time) < MAX_RECORD_SECONDS:
            data = stream.read(CHUNK)
            frames.append(data)
            if (time.time() - start_time) % 1 < 0.1:  # Log every second
                logger.info("Recording in progress: {:.1f} seconds".format(time.time() - start_time))

        logger.info(
            "Recording finished. Duration: {:.1f} seconds. Frames: {}".format(time.time() - start_time, len(frames))
        )
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

            wf = wave.open(temp_file_name, "wb")
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(p.get_sample_size(FORMAT))
            wf.setframerate(RATE)
            wf.writeframes(b"".join(frames))
            wf.close()

            file_size = os.path.getsize(temp_file_name)
            logger.info(f"Audio data written to temporary file. Size: {file_size} bytes")

        # Check if the recording is at least 1 second long
        if len(frames) < RATE / CHUNK:
            logger.info("Recording too short (less than 1 second). Discarding.")
            return

        logger.info(f"Recording length: {len(frames) * CHUNK / RATE:.2f} seconds")

        # Preprocess audio (downsample to 16kHz)
        try:
            logger.info("Starting audio preprocessing with ffmpeg")
            stream = ffmpeg.input(temp_file_name)
            stream = ffmpeg.output(
                stream,
                PROCESSED_OUTPUT_FILENAME,
                ar=16000,
                ac=1,
                acodec="pcm_s16le",
            )
            ffmpeg.run(stream, capture_stdout=True, capture_stderr=True)
            logger.info(f"Audio preprocessing completed. Output: {PROCESSED_OUTPUT_FILENAME}")
        except ffmpeg.Error as e:
            logger.error(f"Error during audio preprocessing: {e.stderr.decode()}")
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
    """Transcribe the audio file using Fireworks API or Groq API as fallback."""
    if not os.path.exists(audio_file):
        logger.error(f"Audio file does not exist: {audio_file}")
        return None

    # Try Fireworks API first
    if FIREWORKS_API_KEY:
        try:
            logger.info("Attempting Fireworks API transcription...")

            with open(audio_file, "rb") as f:
                files = {"file": (os.path.basename(audio_file), f, "audio/wav")}
                headers = {"Authorization": f"Bearer {FIREWORKS_API_KEY}"}
                data = {"model": "whisper-v3", "response_format": "text"}

                logger.debug("Sending request to Fireworks API...")
                response = requests.post(
                    FIREWORKS_ENDPOINT,
                    headers=headers,
                    files=files,
                    data=data,
                    timeout=30,
                )
                response.raise_for_status()

            logger.debug(f"Fireworks API response: {response.text}")
            return response.text.strip()

        except requests.exceptions.RequestException as e:
            logger.error(f"Fireworks API request failed: {str(e)}")
            if hasattr(e, "response"):
                logger.error(f"Fireworks API error response: {e.response.text}")

    # Fallback to Groq API
    if GROQ_API_KEY:
        try:
            logger.info("Attempting Groq API transcription (fallback)...")
            client = Groq(api_key=GROQ_API_KEY)

            # Create a tuple with filename and file object as required by Groq
            with open(audio_file, "rb") as audio:
                file_tuple = (os.path.basename(audio_file), audio, "audio/wav")

                logger.debug("Sending request to Groq API...")
                transcription = client.audio.transcriptions.create(
                    file=file_tuple,
                    model="whisper-large-v3",
                    response_format="text",
                    language="en",
                    temperature=0.0,
                )

            logger.debug(f"Groq API response: {transcription}")
            return transcription.text.strip()

        except Exception as e:
            logger.error(f"Groq API request failed: {str(e)}")
            if hasattr(e, "response"):
                logger.error(f"Groq API error response: {e.response}")

    logger.error("All transcription attempts failed")
    return None


def process_transcription(transcription):
    """Process the transcription using Cerebras API or OpenAI API as fallback."""
    prompt = (
        "For the given transcription with unclear and incorrect grammar, spelling and "
        "capitalization, return a cleaned text that is the exact representation of "
        "the transcript but in a written form with correct grammar, spelling, "
        "capitalization, etc. Do not add any additional text or comments. Do not "
        "give me multiple options. ONLY output the cleaned text. "
        f"<TRANSCRIPT>{transcription}</TRANSCRIPT>"
    )

    logger.info("Prompt for LLM: %s", prompt)
    print(f"Prompt for LLM: {prompt}")  # Console output

    # Try Cerebras API first
    try:
        response = requests.post(
            CEREBRAS_ENDPOINT,
            headers={
                "Authorization": f"Bearer {CEREBRAS_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "llama3.1-8b",
                "messages": [
                    {
                        "role": "system",
                        "content": ("You are a helpful assistant that improves transcriptions."),
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0,
                "max_completion_tokens": -1,
                "stream": False,
            },
            timeout=30,
        )
        response.raise_for_status()
        processed_text = response.json()["choices"][0]["message"]["content"]
    except requests.RequestException as e:
        logger.error("Cerebras API error: %s", e)
        # Fallback to OpenAI API
        try:
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                json={
                    "model": "gpt-4",
                    "messages": [
                        {
                            "role": "system",
                            "content": ("You are a helpful assistant that improves transcriptions."),
                        },
                        {"role": "user", "content": prompt},
                    ],
                },
                timeout=30,
            )
            response.raise_for_status()
            processed_text = response.json()["choices"][0]["message"]["content"]
        except requests.RequestException as e:
            logger.error("OpenAI API error: %s", e)
            return None

    logger.info("Raw LLM output: %s", processed_text)
    print(f"Raw LLM output: {processed_text}")  # Console output

    # Check if the processed text has more than one sentence
    sentences = re.split(r"(?<=[.!?])\s+", processed_text.strip())
    if len(sentences) > 1:
        processed_text += "\n"  # Add an extra newline if there's more than one sentence

    logger.info("Final processed text: %s", processed_text)
    print(f"Final processed text: {processed_text}")  # Console output

    return processed_text


def insert_text_into_active_window(text):
    """Insert the processed text into the active window using xclip and xdotool."""
    try:
        logger.info("Attempting to paste text: %s", text)
        # Copy the text to clipboard
        subprocess.run(
            ["xclip", "-selection", "clipboard"],
            input=text.encode("utf-8"),
            check=True,
        )

        # Simulate Ctrl+V to paste
        subprocess.run(["xdotool", "key", "--clearmodifiers", "ctrl+v"], check=True)

        logger.info("Text pasted into active window successfully")
    except subprocess.CalledProcessError as e:
        logger.error("Failed to paste text into active window: %s", e)
    except FileNotFoundError:
        logger.error("xclip or xdotool not found. Please install them using: " "sudo apt-get install xclip xdotool")


def check_permissions():
    """Check if the script has the necessary permissions."""
    try:
        # Check microphone access
        p = pyaudio.PyAudio()
        stream = p.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            frames_per_buffer=CHUNK,
        )
        stream.stop_stream()
        stream.close()
        p.terminate()

        # Check file writing
        with tempfile.NamedTemporaryFile(mode="w", delete=True) as temp_file:
            temp_file.write("Test")

        logger.info("Permissions check passed")
        return True
    except (OSError, IOError) as e:
        logger.error("Permissions check failed: %s", e)
        return False


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
        logger.error("Error: Insufficient permissions. Please check the log file for details.")
        sys.exit(1)

    # Modified API key validation
    if not (FIREWORKS_API_KEY or GROQ_API_KEY):
        logger.error(
            "Missing required API keys. Please set either FIREWORKS_API_KEY or "
            "GROQ_API_KEY as environment variables."
        )
        sys.exit(1)

    # Set up the keyboard listener
    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()
    logger.info("Keyboard listener started. Press Alt+T to start/stop recording.")

    try:
        # Keep the script running
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received. Exiting...")
    finally:
        listener.stop()
        logger.info("Keyboard listener stopped.")
