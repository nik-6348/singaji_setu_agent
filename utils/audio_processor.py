import streamlit as st
import io
import soundfile as sf
import numpy as np
from typing import List, Tuple, Optional

# Constants
MAX_SYNC_DURATION_SECONDS = 59

def process_audio_and_chunk(
    uploaded_file: io.BytesIO,
    chunk_length_seconds: int = MAX_SYNC_DURATION_SECONDS,
) -> Optional[List[Tuple[io.BytesIO, str]]]:
    """
    Process audio file and split it into chunks for transcription.
    
    Args:
        uploaded_file: The uploaded audio file
        chunk_length_seconds: Length of each chunk in seconds (default: 59)
        
    Returns:
        List of tuples containing (chunk_buffer, time_label) or None if processing fails
    """
    try:
        st.info("🔄 Processing and chunking audio file...")
        
        # Read audio using soundfile (lighter than pydub)
        uploaded_file.seek(0)
        audio_data, sample_rate = sf.read(uploaded_file)
        
        # Convert to mono if stereo
        if len(audio_data.shape) > 1:
            audio_data = np.mean(audio_data, axis=1)
        
        # Calculate chunk size in samples
        chunk_size_samples = int(chunk_length_seconds * sample_rate)
        total_samples = len(audio_data)
        
        chunk_data = []
        for i in range(0, total_samples, chunk_size_samples):
            chunk = audio_data[i:i + chunk_size_samples]
            
            # Calculate time labels
            start_time_s = i / sample_rate
            end_time_s = (i + len(chunk)) / sample_rate
            time_label = f"{start_time_s:.1f}s - {end_time_s:.1f}s"
            
            # Create WAV buffer
            buffer = io.BytesIO()
            sf.write(buffer, chunk, sample_rate, format='WAV')
            buffer.seek(0)
            
            chunk_data.append((buffer, time_label))
        
        num_chunks = len(chunk_data)
        st.success(f"✅ Audio split into {num_chunks} chunks of {chunk_length_seconds}s each.")
        return chunk_data
        
    except Exception as e:
        st.error(f"Audio processing error: {e}")
        return None
