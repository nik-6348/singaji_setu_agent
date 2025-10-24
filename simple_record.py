import streamlit as st
from streamlit_audiorec import st_audiorec
import soundfile as sf
from io import BytesIO
import numpy as np

st.title("🎤 Simple Audio Recorder Test")

# Audio recorder
wav_audio_data = st_audiorec()

if wav_audio_data is not None:
    st.success("✅ Audio recorded!")
    
    # Play the audio
    st.audio(wav_audio_data, format="audio/wav")
    
    try:
        # Analyze the audio
        audio_file = BytesIO(wav_audio_data)
        audio_data, sample_rate = sf.read(audio_file)
        
        # Convert to mono if stereo
        if len(audio_data.shape) > 1:
            audio_data = np.mean(audio_data, axis=1)
        
        # Show stats
        duration = len(audio_data) / sample_rate
        max_amplitude = np.max(np.abs(audio_data))
        
        st.info(f"Duration: {duration:.2f}s")
        st.info(f"Sample Rate: {sample_rate} Hz")
        st.info(f"Max Amplitude: {max_amplitude:.4f}")
        st.info(f"Audio samples: {len(audio_data)}")
        
        # Download button
        st.download_button(
            "📥 Download WAV",
            wav_audio_data,
            "recording.wav",
            "audio/wav"
        )
        
    except Exception as e:
        st.error(f"Error analyzing audio: {e}")
else:
    st.info("🎙️ Click the record button above to start recording")