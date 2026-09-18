import socket
import json
import time
import math
import os
import winsound
from collections import deque

# ==========================================
# CONFIGURATION
# ==========================================
HOST = 'INSERT IP ADDRESS'       # Localhost (where PHD2 is running) i recomend using tailscale ip
PORT = 4400              # Default PHD2 Event Server port
RMS_THRESHOLD_PIXELS = 1.7  # RMS guide error limit that triggers the alarm
RMS_WINDOW_SAMPLES = 30     # Samples used to smooth out isolated jumps/dithers
COOLDOWN_SECONDS = 60    # Minimum time between alarms to prevent spam
AUDIO_FILE = os.path.join(os.path.dirname(__file__), "f16_warning.wav")        # Path to a .wav file (e.g., "C:\\sounds\\alert.wav")
                         # Leave as None to use the default system beep.
# ==========================================

def play_alarm():
    """Plays an audio alert."""
    if AUDIO_FILE:
        winsound.PlaySound(AUDIO_FILE, winsound.SND_FILENAME | winsound.SND_ASYNC)
    else:
        # Fallback to a loud system beep (Frequency: 1000Hz, Duration: 1000ms)
        winsound.Beep(1000, 1000)

def main():
    last_alarm_time = 0
    error_samples = deque(maxlen=RMS_WINDOW_SAMPLES)
    dithering = False
    
    # Create a TCP socket connection to PHD2
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((HOST, PORT))
        print(f"Successfully connected to PHD2 on port {PORT}.")
        print(f"Monitoring for RMS guide errors > {RMS_THRESHOLD_PIXELS} pixels...")
        if AUDIO_FILE and not os.path.isfile(AUDIO_FILE):
            print(f"Warning: Audio file not found: {AUDIO_FILE}")
    except ConnectionRefusedError:
        print("Error: Could not connect to PHD2. Is PHD2 running and is 'Enable Server' checked in the Tools menu?")
        return

    # Use makefile to easily read the stream line-by-line
    with s.makefile('r', encoding='utf-8') as stream:
        for line in stream:
            try:
                data = json.loads(line.strip())

                event = data.get('Event')
                if event in ('DitherStart', 'DitherBegin'):
                    dithering = True
                    error_samples.clear()
                    print("Dithering detected; alarm paused.")
                    continue
                if event in ('DitherEnd', 'DitherComplete'):
                    dithering = False
                    error_samples.clear()
                    print("Dithering finished; alarm resumed.")
                    continue
                
                # We only care about the "GuideStep" event
                if event == 'GuideStep' and not dithering:
                    
                    # PHD2's current event names are RADistanceRaw/DECDistanceRaw.
                    ra_dist = float(data.get('RADistanceRaw', data.get('RADistance', data.get('dx', 0.0))))
                    dec_dist = float(data.get('DECDistanceRaw', data.get('DECDistance', data.get('dy', 0.0))))

                    # Use both axes so one transient jump does not trigger the alarm.
                    sample_error_squared = ra_dist ** 2 + dec_dist ** 2
                    error_samples.append(sample_error_squared)
                    rms_error = math.sqrt(math.fsum(error_samples) / len(error_samples))
                    print(f"Guide error RMS: {rms_error:.2f} px")
                    
                    # Do not evaluate until the window is full; this filters startup spikes too.
                    if (len(error_samples) == RMS_WINDOW_SAMPLES and
                            rms_error > RMS_THRESHOLD_PIXELS):
                        current_time = time.time()
                        
                        # Check if enough time has passed since the last alarm
                        if (current_time - last_alarm_time) > COOLDOWN_SECONDS:
                            print(f"\n[ALARM] High RMS Guide Error Detected! RMS: {rms_error:.2f} px (RA: {ra_dist:.2f}, DEC: {dec_dist:.2f})")
                            play_alarm()
                            last_alarm_time = current_time
                        else:
                            # Silently ignore to prevent audio spam
                            pass
                            
            except json.JSONDecodeError:
                continue
            except Exception as e:
                print(f"An unexpected error occurred: {e}")
                break

if __name__ == "__main__":
    main()