# VoiceFlow

VoiceFlow is a background audio transcription and processing tool for Ubuntu that allows users to quickly transcribe and process their speech using a hotkey combination.

## Installation

1. Clone this repository:
   git clone https://github.com/yourusername/voiceflow.git
   cd voiceflow
   Copy
2. Create a virtual environment and install dependencies:
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   Copy
3. Set up your API keys:
   Edit `voiceflow.py` and replace the placeholder API keys with your actual keys for Groq, Deepgram, and GPT-4.

4. Set up the systemd service:
   sudo cp voiceflow.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable voiceflow.service
   sudo systemctl start voiceflow.service
   Copy

## Usage

1. Press and hold Super + 3 to start recording.
2. Release Super + 3 to stop recording and process the audio.
3. The processed text will be copied to your clipboard and inserted into the active window.

## Features

- Hotkey activation (Super + 3) for audio recording
- Maximum recording duration of 5 minutes
- Automatic transcription using Groq API (fallback to Deepgram Nova 2)
- AI processing of transcription using Groq's Llama model (fallback to GPT-4)
- Visual indicator for recording status
- Autostart on system boot

## Areas for further development or refinement

- Improving the visual indicator (e.g., using custom icons or animations).
- Implementing a method to insert text into the active window (this can be challenging and may require additional libraries or system-specific methods).
- Adding more robust error handling and logging.
- Implementing a configuration file for easy customization of API keys and other settings.

## Configuration

VoiceFlow uses environment variables for API keys. Set them in your shell or add them to your `.bashrc` or `.bash_profile`:

export GROQ_API_KEY=your_groq_api_key
export DEEPGRAM_API_KEY=your_deepgram_api_key
export OPENAI_API_KEY=your_openai_api_key

## Permissions

VoiceFlow requires access to the microphone and the ability to write temporary files. The script will check for these permissions on startup. If you encounter permission issues, ensure that your user has the necessary rights to access the microphone and write to the temporary directory.

## Tray Icon Support

VoiceFlow attempts to create a tray icon for easy access. If your system doesn't support tray icons, the application will still run but without a visible icon. You can still use the hotkey functionality.
