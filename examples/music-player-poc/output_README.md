# Real-Time Notch Filter Music Player

This project implements a real-time audio processor that plays a WAV file while applying a user-adjustable IIR notch filter. The notch filter frequency can be changed interactively during playback.

## Prerequisites

You must have Python 3 installed.

## Setup

1. **Install Dependencies:**
   The required libraries are listed in `requirements.txt`. Install them using pip:
   ```bash
   pip install -r requirements.txt
   ```

2. **Audio File:**
   Ensure you have a `.wav` file (e.g., `test_audio.wav`) to test the player.

## Usage

Run the script from your terminal, providing the path to your WAV file as an argument:

```bash
python3 music_player.py <path_to_your_audio.wav>
```

### Interaction Guide

After the audio starts playing, the console will switch to the control prompt (`>`).

*   **Change Notch Frequency:** To change the center frequency of the notch filter, enter `n <frequency_in_hz>`.
    *   *Example:* `n 500` (Sets the notch to 500 Hz).
    *   *Example:* `n 1500` (Sets the notch to 1500 Hz).
*   **Stop Playback:** To stop the stream and exit the program, enter `s`.

## Implementation Details

*   **`music_player.py`**: Contains the core logic.
    *   Uses `sounddevice.OutputStream` with a non-return callback (`notch_callback`) to process audio chunks in real-time.
    *   The filter uses `scipy.signal.lfilter` and maintains state (`zi`) between callback calls for continuity.
    *   A separate `threading.Thread` handles command-line input, allowing the main audio loop to run uninterrupted while parameters are adjusted.
*   **State Management:** All global state declarations (`global x`) are correctly positioned at the start of the functions as required.
