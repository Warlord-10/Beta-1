from aec_audio_processing import AudioProcessor

# Initialize with specific features
ap = AudioProcessor(
    enable_aec=True,    # Echo cancellation
    enable_ns=True,     # Noise suppression  
    enable_agc=True,    # Automatic gain control
    enable_vad=False     # Voice activity detection
)

# Set audio format
ap.set_stream_format(
    sample_rate_in=16000,      # Input sample rate (Hz)
    channel_count_in=1,        # Input channels
    sample_rate_out=16000,     # Output sample rate (Hz) 
    channel_count_out=1        # Output channels
)

# Set reverse stream for echo cancellation
ap.set_reverse_stream_format(24000, 1)

# Set stream delay for echo cancellation
ap.set_stream_delay(50)  # 50ms delay


# Check feature status
print(f"AEC enabled: {ap.aec_enabled()}")
print(f"NS enabled: {ap.ns_enabled()}")
print(f"AGC enabled: {ap.agc_enabled()}")
