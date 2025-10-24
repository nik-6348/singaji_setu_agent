import streamlit as st
import numpy as np
from streamlit_webrtc import webrtc_streamer, WebRtcMode
import queue
import time
from io import BytesIO
import soundfile as sf

st.title("🎤 Live Recording Test")

# Initialize session state
if 'audio_frames' not in st.session_state:
    st.session_state.audio_frames = []
if 'is_recording' not in st.session_state:
    st.session_state.is_recording = False
if 'audio_buffer' not in st.session_state:
    st.session_state.audio_buffer = None

# WebRTC streamer
webrtc_ctx = webrtc_streamer(
    key="test-recorder",
    mode=WebRtcMode.SENDONLY,
    audio_receiver_size=1024,
    media_stream_constraints={"audio": True, "video": False},
)

# Handle recording state
if webrtc_ctx.state.playing and not st.session_state.is_recording:
    st.session_state.is_recording = True
    st.session_state.audio_frames = []
    st.success("🎤 Recording started!")
elif not webrtc_ctx.state.playing and st.session_state.is_recording:
    st.session_state.is_recording = False
    if st.session_state.audio_frames:
        try:
            combined_audio = np.concatenate(st.session_state.audio_frames)
            st.session_state.audio_buffer = {
                'data': combined_audio,
                'sample_rate': 48000
            }
            st.success("✅ Recording saved!")
        except Exception as e:
            st.error(f"Error: {e}")

# Collect audio frames
if st.session_state.is_recording and webrtc_ctx.audio_receiver:
    try:
        audio_frames = webrtc_ctx.audio_receiver.get_frames(timeout=0.1)
        for frame in audio_frames:
            sound_array = frame.to_ndarray()
            if len(sound_array.shape) > 1:
                sound_array = np.mean(sound_array, axis=1)
            if len(sound_array) > 0:
                st.session_state.audio_frames.append(sound_array)
    except queue.Empty:
        pass

# Display status
if st.session_state.is_recording:
    st.info(f"📊 Frames collected: {len(st.session_state.audio_frames)}")
elif st.session_state.audio_buffer:
    st.success("🎵 Recording complete!")
    try:
        audio_bytes = BytesIO()
        sf.write(audio_bytes, st.session_state.audio_buffer['data'], 
                st.session_state.audio_buffer['sample_rate'], format='WAV')
        st.audio(audio_bytes.getvalue(), format="audio/wav")
        
        duration = len(st.session_state.audio_buffer['data']) / st.session_state.audio_buffer['sample_rate']
        st.info(f"Duration: {duration:.1f}s | Sample Rate: {st.session_state.audio_buffer['sample_rate']} Hz")
    except Exception as e:
        st.error(f"Playback error: {e}")

if st.button("🔄 Reset"):
    st.session_state.audio_frames = []
    st.session_state.audio_buffer = None
    st.session_state.is_recording = False
    st.rerun()