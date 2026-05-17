# Tinnitus Notch Therapy Player — Built by Guild

## Motivation

My father has **tinnitus** — a condition where the brain perceives a constant phantom tone. One evidence-based treatment is **Tailor-Made Notched Music Training (TMNMT)**: you identify the patient's tinnitus frequency, then remove (notch out) that exact frequency from music they listen to daily. Over time, this suppresses the phantom tone through lateral inhibition in the auditory cortex.

I needed a player that could do this in real-time with adjustable frequency. Instead of building it myself, I had Guild do it — as a proof of concept that an autonomous agent team can produce working, verified software.

## What Guild Built

A Python music player that:
- Loads any WAV file
- Applies a real-time IIR notch filter via `scipy.signal.iirnotch` + `lfilter`
- Maintains filter state (`zi`) across audio chunks for glitch-free playback
- Uses `sounddevice.OutputStream` callback for real-time processing
- Accepts keyboard input to change the notch frequency during playback

## How Guild Built It

**Team composition:** fast coder (Gemma 4 4B) + strict e2e verifier (Gemma 4 26B)

```
Iteration 1:
  Coder (4B)      → wrote all files
  E2E Runner (26B) → ran DSP unit test + live 3s playback test → FAIL (runtime error)
  
Iteration 2:
  Coder (4B)      → rewrote with fix based on error feedback
  E2E Runner (26B) → all checks pass, no stderr errors → PASS
```

The e2e runner verifies:
1. Filter math correctness (FFT analysis confirms target frequency attenuation)
2. App runs 3 seconds without crashes or callback errors
3. No tracebacks in stderr (catches sounddevice callback failures)

## Running the Player

```bash
pip install numpy scipy sounddevice soundfile

# Create a test tone (440Hz + your tinnitus frequency)
python3 -c "
import numpy as np, soundfile as sf
sr = 44100; t = np.linspace(0, 30, sr*30, endpoint=False).astype('float32')
audio = 0.3*np.sin(2*3.14159*440*t) + 0.3*np.sin(2*3.14159*1000*t)
sf.write('test.wav', audio, sr)
"

# Play with notch filter (removes 1000Hz)
python3 music_player.py test.wav
# Then type: n 1000  (to notch out 1000Hz)
```

## Files

| File | Description |
|------|-------------|
| `team_music.toml` | Team: coder → e2e_runner loop (max 5 iterations) |
| `coder.toml` | Coder block — 4B model, tool-use enforced |
| `e2e_runner.toml` | Verifier — 26B model, runs DSP test + live playback check |
| `output_music_player.py` | Final code produced by Guild |
| `output_requirements.txt` | Dependencies |
| `output_README.md` | Generated user documentation |
| `execution_trace.json` | Full agent conversation trace |

## Reproducing

```bash
cd your-project/
guild init
guild config --set provider.base_url=http://<ollama-host>:11434
guild config --set escalation.escalation_chain=gemma4-26b-moe-agent

# Copy block definitions
mkdir -p .guild/blocks
cp examples/music-player-poc/{coder,e2e_runner,team_music}.toml .guild/blocks/

# Run the team
guild team -t music-builder "Create a Python music player with real-time notch filter..."
```
