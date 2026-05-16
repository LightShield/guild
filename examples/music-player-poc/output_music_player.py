import numpy as np
import sounddevice as sd
import soundfile as sf
import scipy.signal as signal
import sys
import threading

# Global variables for state management
global_read_position = 0
notch_freq = 1000.0
fs = 44100.0
stop_playback = False
audio_data = None
b_coeffs = None
a_coeffs = None
zi = None

def update_notch_filter(freq, fs):
    global b_coeffs, a_coeffs, zi
    # Ensure frequency is within valid range (Nyquist limit)
    if freq <= 0 or freq >= fs / 2:
        return
    
    # Design notch filter
    # Q factor of 30 for a sharp notch
    Q = 30.0
    b, a = signal.iirnotch(freq, Q, fs)
    
    # If zi is already initialized, we need to pad/adjust it for the new filter order
    # But for simplicity in this real-time implementation, we'll re-init zi 
    # or rely on the fact that lfilter_zi handles the order.
    # However, changing coefficients mid-stream is tricky with zi.
    # For a production app, we'd use a smoother transition or fixed order.
    # Here we just update b, a and reset zi to prevent errors, 
    # accepting a tiny click for the sake of the exercise.
    b_coeffs = b
    a_coeffs = a
    
    # Re-initialize zi with the correct shape for the new coefficients
    new_zi = signal.lfilter_zi(b, a)
    zi = new_zi

def audio_callback(outdata, frames, time, status):
    global global_read_position, audio_data, b_coeffs, a_coeffs, zi, stop_playback

    if status:
        print(s_status := f"Status: {status}", file=sys.stderr)

    if stop_playback or audio_data is None:
        outdata.fill(0)
        return

    # Calculate chunk boundaries
    start = global_read_position
    end = start + frames
    
    # Check if we reached the end of the file
    if end > len(audio_data):
        # Pad with zeros if we reach the end
        chunk = np.zeros(frames)
        # Fill the available part
        available = len(audio_data) - start
        if available > 0:
            chunk[:available] = audio_data[start:]
        outdata[:available, 0] = chunk[:available]
        outdata[available:, 0] = 0
        stop_playback = True
        return

    # Get the chunk of audio
    chunk = audio_data[start:end]
    
    # Apply Notch Filter
    # Crucial rule: unpack the tuple (filtered_data, new_state)
    if b_coeffs is not None and a_coeffs is not None:
        # We use the same zi across chunks to maintain continuity
        filtered_chunk, next_zi = signal.lfilter(b_coeffs, a_coeffs, chunk, zi=zi)
        zi = next_zi
        outdata[:len(filtered_chunk), 0] = filtered_chunk
    else:
        outdata[:len(chunk), 0] = chunk

    # Update global position
    global_read_position = end

def input_thread():
    global notch_freq, stop_playback
    print("Controls:")
    print(" - Enter 'f <frequency>' to change notch frequency (e.g., 'f 1000')")
    print(" - Enter 'q' to quit")
    
    while not stop_playback:
        try:
            cmd = input().strip().split()
            if not cmd:
                continue
            
            if cmd[0] == 'q':
                stop_playback = True
                break
            elif cmd[0] == 'f':
                if len(cmd) > 1:
                    new_f = float(cmd[1])
                    print(f"Changing notch frequency to: {new_f} Hz")
                    update_notch_filter(new_f, fs)
                else:
                    print("Usage: f <frequency>")
            else:
                print("Unknown command.")
        except EOFError:
            stop_playback = True
            break
        except ValueError:
            print("Invalid frequency value.")
        except Exception as e:
            print(f"Error: {e}")

def main():
    global audio_data, fs, stop_playback, b_coeffs, a_coeffs, zi

    if len(sys.argv) < 2:
        print("Usage: python music_player.py <path_to_wav>")
        return

    file_path = sys.argv[1]

    try:
        # Load audio file
        audio_data, fs = sf.read(file_path)
        # Ensure mono for simplicity in this demo
        if len(audio_data.shape) > 1:
            audio_data = audio_data[:, 0]
        
        print(f"Loaded: {file_path}")
        print(f"Sample Rate: {fs} Hz")
        print(f"Duration: {len(audio_data)/fs:.2f} seconds")
        
    except Exception as e:
        print(f"Error loading file: {e}")
        return

    # Initialize filter
    update_notch_filter(notch_freq, fs)

    # Start input thread
    t = threading.Thread(target=input_thread, daemon=True)
    t.start()

    # Start audio stream
    try:
        with sd.OutputStream(channels=1, callback=audio_callback, samplerate=fs, blocksize=1024) as stream:
            while not stop_playback:
                sd.sleep(100)
    except Exception as e:
        print(f"Stream error: {e}")
    finally:
        print("Playback stopped.")

if __name__ == "__main__":
    main()
