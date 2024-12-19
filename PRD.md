# VoiceFlow - Voice-to-Text with AI Enhancement

## Overview

VoiceFlow is a Linux-based desktop application that provides real-time voice-to-text transcription with AI-powered text enhancement. It allows users to quickly convert speech to professionally formatted text directly into any active window.

## Core Features

1. **Voice Recording**

   - Triggered by Alt+T keyboard shortcut
   - Real-time audio capture using PyAudio
   - Maximum recording duration: 5 minutes
   - Supports 44.1kHz sampling rate with 16-bit depth

2. **Audio Processing**

   - Automatic audio preprocessing using FFmpeg
   - Downsampling to 16kHz for optimal transcription
   - Temporary file management for secure processing

3. **Transcription Service**

   - Primary: Fireworks AI API (Whisper v3 model)
   - Fallback: Groq API (Whisper Large v3 model)
   - Real-time speech-to-text conversion

4. **AI Enhancement**

   - Primary: Cerebras API (Llama 3.1 8B model)
   - Fallback: OpenAI API (GPT-4)
   - Improves grammar, spelling, and formatting
   - Maintains original meaning while enhancing readability

5. **Output Handling**
   - Automatic clipboard copying
   - Direct insertion into active window
   - Support for multi-sentence formatting

## Technical Requirements

- Linux operating system
- Python environment
- Required system packages: xclip, xdotool
- Audio input device access
- Internet connection for API access

## Dependencies

- API Keys Required:
  - Primary: FIREWORKS_API_KEY or GROQ_API_KEY
  - Secondary: CEREBRAS_API_KEY or OPENAI_API_KEY
- Python packages:
  - pyaudio
  - ffmpeg-python
  - requests
  - python-dotenv
  - pynput
  - pyperclip

## Security Features

- Environment variable-based API key management
- Secure temporary file handling
- Single instance enforcement
- Rotating log system

## User Experience

- Simple keyboard shortcut activation (Alt+T)
- No GUI required - works with any active window
- Automatic text insertion
- Minimal user interaction needed

## Performance

- Real-time audio processing
- Efficient memory management
- Automatic cleanup of temporary files
- Fallback systems for API failures

## Logging and Monitoring

- Detailed logging system with rotation
- Debug information for troubleshooting
- API response tracking
- Error handling and reporting
