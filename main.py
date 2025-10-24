# app.py

import streamlit as st
import soundfile as sf
import numpy as np
import time
import json
from io import BytesIO
try:
    from streamlit_audiorec import st_audiorec
except ImportError:
    st_audiorec = None

# Local imports
from services.transcription_service import TranscriptionService
from services.gemini_service import GeminiService
from utils.ui_components import apply_custom_styling, get_default_schema
from config.settings import (
    APP_TITLE,
    APP_ICON,
    APP_LAYOUT,
    GCS_BUCKET_NAME,
    get_gcp_project_id,
    GCP_LOCATION,
    validate_environment,
)

# --- HELPER FUNCTIONS ---
def format_time(seconds: float) -> str:
    """Format seconds into MM:SS format."""
    seconds = max(0, int(seconds))
    m, s = divmod(seconds, 60)
    return f"{m:02d}:{s:02d}"


def initialize_services():
    """Initialize real API services and store them in session state."""
    if "services_initialized" not in st.session_state:
        # Validate environment variables first
        if not validate_environment():
            st.error(
                "❌ Environment validation failed. Please check the console for missing variables."
            )
            st.stop()

        # Initialize Transcription Service
        project_id = get_gcp_project_id()
        if not project_id:
            st.error(
                "❌ GCP Project ID not found. Please set GCP_PROJECT_ID environment variable or check service account credentials."
            )
            st.session_state.transcription_service = None
        else:
            st.session_state.transcription_service = TranscriptionService(
                gcs_bucket_name=GCS_BUCKET_NAME,
                gcp_project_id=project_id,
                gcp_location=GCP_LOCATION,
            )

        # Initialize Gemini Service
        st.session_state.gemini_service = GeminiService()
        st.session_state.services_initialized = True


def initialize_session_state():
    """Initialize or reset all session state variables for the workflow."""
    if "current_step" not in st.session_state:
        st.session_state.current_step = "workflow_selection"
        st.session_state.workflow_type = None
        st.session_state.audio_buffer = None
        st.session_state.transcript = None
        st.session_state.edited_transcript = None
        st.session_state.gemini_result = None


# --- CORE PROCESSING LOGIC ---


def process_audio_upload(uploaded_file):
    """Handles the processing of an uploaded audio file."""
    with st.spinner("Processing uploaded audio file..."):
        try:
            # Reset file pointer
            uploaded_file.seek(0)
            
            # Try different approaches based on file type
            file_extension = uploaded_file.name.lower().split('.')[-1]
            
            if file_extension in ['m4a', 'mp4', 'aac']:
                # For M4A files, show conversion message
                st.error("❌ M4A format not directly supported by soundfile.")
                st.info("🔄 **Solution Options:**")
                st.markdown("""
                1. **Online Converter:** Use [CloudConvert](https://cloudconvert.com/m4a-to-wav) to convert M4A → WAV
                2. **Local Tools:** Use VLC, Audacity, or FFmpeg to convert
                3. **Command Line:** `ffmpeg -i input.m4a output.wav`
                """)
                st.warning("Please convert your file to WAV format and upload again.")
                return
            
            # Read audio using soundfile
            audio_data, sample_rate = sf.read(uploaded_file)
            
            # Convert to mono if stereo
            if len(audio_data.shape) > 1:
                audio_data = np.mean(audio_data, axis=1)
            
            # Ensure audio data is not empty
            if len(audio_data) == 0:
                st.error("❌ Audio file appears to be empty or corrupted.")
                return
            
            # Store as dict with data and sample rate
            st.session_state.audio_buffer = {
                'data': audio_data,
                'sample_rate': sample_rate
            }
            st.toast("✅ Audio processed successfully!", icon="🎵")
            st.session_state.current_step = "transcribe"
            st.rerun()
            
        except sf.LibsndfileError as e:
            st.error(f"❌ Unsupported audio format: {uploaded_file.name}")
            st.info("💡 **Supported formats:** WAV, FLAC")
            st.info("🔄 **For MP3/M4A:** Please convert to WAV format first")
        except Exception as e:
            st.error(f"❌ Failed to process audio file: {e}")
            st.info("💡 Try converting your file to WAV format for best compatibility.")


def run_transcription():
    """Runs the transcription process on the audio buffer."""
    if st.session_state.audio_buffer:
        with st.spinner("🤖 Transcribing audio... This may take a few minutes."):
            try:
                # Convert audio data to WAV bytes
                audio_buffer = st.session_state.audio_buffer
                audio_file_like = BytesIO()
                sf.write(audio_file_like, audio_buffer['data'], audio_buffer['sample_rate'], format='WAV')
                audio_file_like.seek(0)
                audio_file_like.name = "processed_audio.wav"

                transcript_text = (
                    st.session_state.transcription_service.transcribe_full_file(
                        audio_file_like, language_code="hi-IN"
                    )
                )
                if transcript_text:
                    st.session_state.transcript = transcript_text
                    st.session_state.edited_transcript = transcript_text
                    st.session_state.current_step = "analyze"
                    st.success("✅ Transcription complete!")
                    st.rerun()
                else:
                    st.warning("Transcription returned an empty result.")
            except Exception as e:
                st.error(f"❌ Transcription failed: {e}")


def run_analysis():
    """Runs the Gemini analysis on the transcript."""
    transcript = st.session_state.get("edited_transcript")
    if transcript:
        # with st.spinner("🚀 Analyzing transcript with Gemini AI..."):
            try:
                schema = get_default_schema()
                schema_json = json.dumps(schema, indent=2)

                result = st.session_state.gemini_service.generate_json_payload(
                    schema_json, transcript
                )
                if result:
                    st.session_state.gemini_result = result
                    st.session_state.current_step = "export"
                    st.success("✅ AI analysis complete!")
                    st.rerun()
                else:
                    st.warning("AI analysis returned an empty result.")
            except Exception as e:
                st.error(f"❌ Payload generation failed: {e}")


# --- UI RENDERING FUNCTIONS (VIEWS) ---


def render_sidebar():
    """Renders the sidebar for navigation and status."""
    with st.sidebar:
        st.markdown("---")
        steps = {
            "workflow_selection": "1. Audio Source",
            "input": "2. Record / Upload",
            "transcribe": "3. Transcribe",
            "analyze": "4. Analyze",
            "export": "5. Export",
        }
        current_step_index = list(steps.keys()).index(st.session_state.current_step)
        for i, (step_id, step_name) in enumerate(steps.items()):
            if i < current_step_index:
                st.markdown(f"✔️ ~~{step_name}~~")
            elif i == current_step_index:
                st.markdown(f"➡️ **{step_name}**")
            else:
                st.markdown(f"⏳ _{step_name}_")

        st.markdown("---")
        if st.button("🔄 Start Over", use_container_width=True, type="secondary"):
            for key in list(st.session_state.keys()):
                if key not in [
                    "services_initialized",
                    "transcription_service",
                    "gemini_service",
                ]:
                    del st.session_state[key]
            # Reinitialize session state
            initialize_session_state()
            st.rerun()


def render_workflow_selection_view():
    """UI for selecting between live recording and file upload."""
    st.header("Step 1: Choose Your Audio Source")
    st.write("Select how you want to provide the farmer interview audio.")
    col1, col2 = st.columns(2)
    with col1:
        if st.button(
            "🎙️ **Start Recording**", use_container_width=True, key="start_rec"
        ):
            st.session_state.workflow_type = "live"
            st.session_state.current_step = "input"
            st.rerun()
    with col2:
        if st.button(
            "📁 **Upload Audio File**", use_container_width=True, key="start_upload"
        ):
            st.session_state.workflow_type = "upload"
            st.session_state.current_step = "input"
            st.rerun()


def render_input_view():
    """UI for the audio input step (either recording or uploading)."""
    st.header("Step 2: Provide Audio Input")
    workflow = st.session_state.get("workflow_type")
    if workflow == "live":
        render_live_recorder()
    elif workflow == "upload":
        render_file_uploader()
    else:
        st.warning("Please select a workflow first.")
        if st.button("⬅️ Go Back"):
            st.session_state.current_step = "workflow_selection"
            st.rerun()


def render_live_recorder():
    """UI for live audio recording using streamlit-audiorec."""

    
    st.subheader("Live Audio Recorder")
    st.info("🎙️ Click the record button below to start recording")
    
    # Audio recorder component
    wav_audio_data = st_audiorec()
    
    if wav_audio_data is not None:
        try:
            # Convert bytes to numpy array
            audio_file = BytesIO(wav_audio_data)
            audio_data, sample_rate = sf.read(audio_file)
            
            # Convert to mono if stereo
            if len(audio_data.shape) > 1:
                audio_data = np.mean(audio_data, axis=1)
            
            # Store in session state
            st.session_state.audio_buffer = {
                'data': audio_data,
                'sample_rate': sample_rate
            }
            
            # Show audio info
            duration = len(audio_data) / sample_rate
            max_amplitude = np.max(np.abs(audio_data)) if len(audio_data) > 0 else 0
            
            st.success("✅ Recording captured successfully!")
            st.info(f"📊 Duration: {format_time(duration)} | Sample Rate: {sample_rate} Hz | Max Amplitude: {max_amplitude:.4f}")
            
            # Play recorded audio
            st.audio(wav_audio_data, format="audio/wav")
            
            if st.button(
                "Continue to Transcription ➡️", type="primary", use_container_width=True
            ):
                st.session_state.current_step = "transcribe"
                st.rerun()
                
        except Exception as e:
            st.error(f"Error processing recorded audio: {e}")
    else:
        st.info("📊 No recording yet. Use the recorder above to capture audio.")


def render_file_uploader():
    """UI for uploading an audio file."""
    st.subheader("Upload Audio File")
    st.info("📋 **Recommended:** WAV or FLAC format for best compatibility")
    st.warning("⚠️ **Note:** M4A files need conversion to WAV first")
    
    uploaded_file = st.file_uploader(
        "Choose audio file (WAV, FLAC recommended)",
        type=["wav", "flac", "mp3", "m4a"],
        label_visibility="collapsed",
    )
    if uploaded_file:
        st.audio(uploaded_file, format=uploaded_file.type)
        if st.button(
            "Process and Continue ➡️", type="primary", use_container_width=True
        ):
            process_audio_upload(uploaded_file)


def render_transcription_view():
    """UI for initiating and reviewing transcription."""
    st.header("Step 3: AI Transcription")
    if not st.session_state.get("audio_buffer"):
        st.warning("No audio data found. Please go back to Step 2.")
        return
    st.info(
        "Your audio is ready for transcription. This may take a few minutes for long recordings."
    )
    
    try:
        # Convert audio buffer to bytes for playback
        audio_buffer = st.session_state.audio_buffer
        audio_bytes = BytesIO()
        sf.write(audio_bytes, audio_buffer['data'], audio_buffer['sample_rate'], format='WAV')
        st.audio(audio_bytes.getvalue(), format="audio/wav")
    except Exception as e:
        st.warning(f"Could not preview audio: {e}")
    if st.button("🎙️ **Start Transcription**", type="primary", use_container_width=True):
        run_transcription()


def render_analysis_view():
    """UI for reviewing transcript and running analysis."""
    st.header("Step 4: AI Analysis")
    transcript = st.session_state.get("transcript")
    if not transcript:
        st.warning("No transcript found. Please complete Step 3 first.")
        return
    st.info(
        "Review the transcript below. Edit if necessary before running the AI analysis."
    )
    edited = st.text_area(
        "**Editable Transcript**",
        value=st.session_state.get("edited_transcript", transcript),
        height=250,
    )
    st.session_state.edited_transcript = edited
    if st.button(
        "🚀 **Generate Survey Data**", type="primary", use_container_width=True
    ):
        run_analysis()


def render_export_view():
    """UI for viewing and exporting final results."""
    st.header("🎉 Step 5: Complete!")
    st.balloons()
    st.success(
        "Your farmer interview has been fully processed. All data is ready for download."
    )

    payload = st.session_state.get("gemini_result")
    transcript = st.session_state.get("edited_transcript")
    audio_buffer = st.session_state.get("audio_buffer")

    if not all([payload, transcript, audio_buffer]):
        st.error("Missing data. Please ensure all previous steps are complete.")
        return

    with st.container(border=True):
        farmer_name = payload.get("farmerDetails", {}).get("farmerName", "N/A")
        summary = payload.get("interviewMetadata", {}).get(
            "summary", "No summary available."
        )
        st.markdown(f"#### 📋 Summary for: {farmer_name}")
        st.markdown(summary)

    tab1, tab2, tab3 = st.tabs(["📊 Survey Data (JSON)", "📄 Transcript", "🎵 Audio"])
    with tab1:
        st.json(payload)
        st.download_button(
            "📥 Download JSON",
            json.dumps(payload, indent=2, ensure_ascii=False),
            f"survey_{int(time.time())}.json",
            "application/json",
            use_container_width=True,
        )
    with tab2:
        st.text(transcript)
        st.download_button(
            "📄 Download Transcript (.txt)",
            transcript,
            f"transcript_{int(time.time())}.txt",
            "text/plain",
            use_container_width=True,
        )
    with tab3:
        # Convert audio buffer to bytes
        audio_bytes_io = BytesIO()
        sf.write(audio_bytes_io, audio_buffer['data'], audio_buffer['sample_rate'], format='WAV')
        audio_bytes = audio_bytes_io.getvalue()
        
        st.audio(audio_bytes, format="audio/wav")
        st.download_button(
            "🎵 Download Audio (.wav)",
            audio_bytes,
            f"interview_{int(time.time())}.wav",
            "audio/wav",
            use_container_width=True,
        )


def main():
    """Main application function."""
    st.set_page_config(page_title=APP_TITLE, page_icon=APP_ICON, layout=APP_LAYOUT)
    apply_custom_styling()

    initialize_session_state()
    initialize_services()

    # --- Persistent App Header ---
    st.markdown(
        f"<h1 style='text-align: center;'>{APP_ICON} {APP_TITLE}</h1>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p style='text-align: center; color: #7f8c8d;'>Intelligent processing of farmer interview surveys from audio recordings</p>",
        unsafe_allow_html=True,
    )
    st.markdown("---")

    render_sidebar()

    step_views = {
        "workflow_selection": render_workflow_selection_view,
        "input": render_input_view,
        "transcribe": render_transcription_view,
        "analyze": render_analysis_view,
        "export": render_export_view,
    }
    current_view = step_views.get(st.session_state.current_step)
    if current_view:
        current_view()
    else:
        st.error("Invalid state. Please start over.")


if __name__ == "__main__":
    main()
