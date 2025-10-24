# services/transcription_service.py
import streamlit as st
import os
import time
import uuid
import soundfile as sf
import numpy as np
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed
from google.cloud import speech
from google.cloud import storage
from google.api_core.client_options import ClientOptions  # noqa: F401
from typing import Optional
from config.settings import get_service_account_credentials


class TranscriptionService:
    """
    Handles audio transcription using Google Cloud Speech-to-Text v1p1beta1
    with real-time dashboard.
    """

    def __init__(self, gcs_bucket_name: str, gcp_project_id: str, gcp_location: str):
        self.creds_path = get_service_account_credentials()
        self.gcs_bucket_name = gcs_bucket_name
        self.project_id = gcp_project_id
        self.location = gcp_location

        if not self.creds_path:
            st.error("❌ Google Cloud credentials not set.")
            self.speech_client = None
            self.storage_client = None
            return

        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = self.creds_path

        try:
            # Initialize v1p1beta1 client
            self.speech_client = speech.SpeechClient()
            self.storage_client = storage.Client()
            self._ensure_bucket_exists()
        except Exception as e:
            st.error(f"❌ Failed to initialize clients: {e}")
            self.speech_client = None
            self.storage_client = None

    def _ensure_bucket_exists(self):
        """Ensure the GCS bucket exists, create it if it doesn't."""
        try:
            bucket = self.storage_client.bucket(self.gcs_bucket_name)
            if not bucket.exists():
                st.info(f"🪣 Creating GCS bucket: {self.gcs_bucket_name}")
                bucket = self.storage_client.create_bucket(
                    self.gcs_bucket_name, location=self.location
                )
                st.success(f"✅ Created GCS bucket: {self.gcs_bucket_name}")
        except Exception as e:
            st.warning(f"⚠️ Could not verify/create GCS bucket: {e}")
            st.info("You may need to create the bucket manually or check permissions.")

    def _upload_to_gcs(self, audio_bytes: BytesIO, destination_blob_name: str) -> str:
        """Uploads audio data to a GCS bucket and returns the GCS URI."""
        try:
            if not self.storage_client:
                raise Exception("Storage client not initialized")
            
            bucket = self.storage_client.bucket(self.gcs_bucket_name)
            blob = bucket.blob(destination_blob_name)
            audio_bytes.seek(0)
            
            # Check if audio_bytes has content
            content = audio_bytes.read()
            if len(content) == 0:
                raise Exception("Audio file is empty")
            
            # Check file size and warn if large
            file_size_mb = len(content) / (1024 * 1024)
            if file_size_mb > 50:
                st.warning(f"⚠️ Large file: {file_size_mb:.1f}MB - this may take time to upload")
            
            audio_bytes.seek(0)  # Reset for upload
            
            # Set content type
            content_type = "audio/wav"
            
            # Upload with timeout settings
            blob.upload_from_file(
                audio_bytes, 
                content_type=content_type,
                timeout=300  # 5 minutes timeout
            )
            
            st.success(f"✅ Uploaded {file_size_mb:.1f}MB to GCS")
            return f"gs://{self.gcs_bucket_name}/{destination_blob_name}"
            
        except Exception as e:
            if "timeout" in str(e).lower():
                st.error(f"⏰ Upload timeout - file too large ({file_size_mb:.1f}MB)")
                st.info("💡 Try using a shorter audio file or better internet connection")
            else:
                st.error(f"GCS Upload Failed: {e}")
            raise

    def transcribe_chunks(
        self, audio_chunks: list[tuple], language_code: str = "hi-IN"
    ) -> Optional[str]:
        """
        Transcribes audio chunks with real-time dashboard.
        """
        if not self.speech_client or not self.storage_client:
            st.error("Clients not initialized. Cannot transcribe.")
            return None

        full_transcript_parts = []
        live_dashboard = st.empty()
        start_time = time.time()

        try:
            for i, (chunk_buffer, time_label) in enumerate(audio_chunks):
                # Upload chunk to GCS for processing
                unique_filename = f"chunk-{uuid.uuid4()}.wav"
                try:
                    gcs_uri = self._upload_to_gcs(chunk_buffer, unique_filename)
                except Exception as e:
                    st.warning(f"Failed to upload chunk {i + 1}: {e}")
                    continue

                # Configure transcription for this chunk
                config = speech.RecognitionConfig(
                    language_code=language_code,
                    enable_automatic_punctuation=True,
                    model="telephony",
                )

                audio = speech.RecognitionAudio(uri=gcs_uri)

                # Process chunk
                try:
                    operation = self.speech_client.long_running_recognize(
                        config=config, audio=audio
                    )
                    response = operation.result()

                    # Extract transcript
                    chunk_transcript = ""
                    if response.results:
                        chunk_transcript = " ".join(
                            result.alternatives[0].transcript
                            for result in response.results
                        )

                    full_transcript_parts.append(chunk_transcript)

                    # Clean up the uploaded chunk
                    try:
                        bucket = self.storage_client.bucket(self.gcs_bucket_name)
                        blob = bucket.blob(unique_filename)
                        blob.delete()
                    except Exception:
                        pass

                except Exception as e:
                    st.warning(f"Chunk {i + 1} transcription failed: {e}")
                    full_transcript_parts.append(
                        f"[Chunk {i + 1} failed to transcribe]"
                    )

                # Update live dashboard
                elapsed_time = time.time() - start_time
                full_text_so_far = " ".join(full_transcript_parts)

                with live_dashboard.container():
                    st.subheader("🔴 Live Transcription Dashboard")
                    prog_col, time_col = st.columns(2)
                    prog_col.metric("Progress", f"{i + 1}/{len(audio_chunks)} Chunks")
                    time_col.metric("Time Elapsed", f"{elapsed_time:.1f}s")

                    st.progress((i + 1) / len(audio_chunks))

                    with st.expander("📜 View Live Transcript", expanded=True):
                        st.markdown(full_text_so_far)

                    # Show current chunk info
                    st.info(f"🎯 Processing: {time_label}")

            total_time = time.time() - start_time
            final_transcript = " ".join(full_transcript_parts)

            # Clear dashboard and show completion
            live_dashboard.empty()
            st.success(f"✅ Transcription complete in {total_time:.2f} seconds!")

            st.session_state.performance_metrics = {
                "total_time": total_time,
                "chunks_processed": len(audio_chunks),
            }

            return final_transcript

        except Exception as e:
            st.error(f"Transcription failed: {e}")
            return " ".join(full_transcript_parts) if full_transcript_parts else None

    def transcribe_full_file(
        self, uploaded_file, language_code: str = "hi-IN"
    ) -> Optional[str]:
        """
        Transcribes a full uploaded file using chunking for large files.
        """
        if not self.speech_client or not self.storage_client:
            st.error("Clients not initialized. Cannot transcribe.")
            return None

        try:
            # Handle different input types
            if hasattr(uploaded_file, 'read'):
                uploaded_file.seek(0)
                if hasattr(uploaded_file, 'getvalue'):
                    audio_data, original_sample_rate = sf.read(uploaded_file)
                else:
                    audio_data, original_sample_rate = sf.read(uploaded_file)
            else:
                source = BytesIO(uploaded_file)
                audio_data, original_sample_rate = sf.read(source)
            
            st.info(f"📊 Original: {len(audio_data)} samples at {original_sample_rate}Hz")
            
            # Convert to mono if stereo
            if len(audio_data.shape) > 1:
                audio_data = np.mean(audio_data, axis=1)
            
            # Keep original sample rate to avoid any data loss
            target_sample_rate = original_sample_rate  # No resampling = no data loss
            
            # Optional: Only resample if really needed (very high sample rates)
            if original_sample_rate > 48000:
                target_sample_rate = 16000
                try:
                    from scipy import signal
                    # Use scipy for proper resampling
                    num_samples = int(len(audio_data) * target_sample_rate / original_sample_rate)
                    audio_data = signal.resample(audio_data, num_samples)
                    st.info(f"🔄 Resampled: {original_sample_rate}Hz → {target_sample_rate}Hz (SciPy)")
                except ImportError:
                    # Fallback: keep original rate to avoid data loss
                    target_sample_rate = original_sample_rate
                    st.info(f"📊 Keeping original sample rate: {original_sample_rate}Hz (no SciPy)")
            else:
                st.info(f"📊 Using original sample rate: {original_sample_rate}Hz (optimal)")
            
            # Normalize audio levels for better transcription
            audio_data = audio_data / np.max(np.abs(audio_data)) * 0.8
            
            # Apply noise reduction (simple)
            audio_data = self._simple_noise_reduction(audio_data)
            
            # Calculate duration
            duration_seconds = len(audio_data) / target_sample_rate
            
            st.success(f"🕰️ Audio duration: {duration_seconds:.1f} seconds")
            st.success(f"📊 Audio samples: {len(audio_data):,} at {target_sample_rate}Hz")
            
            # Validate audio quality
            if duration_seconds < 10:
                st.warning("⚠️ Very short audio detected. Check if file uploaded correctly.")
            elif duration_seconds > 3600:  # More than 1 hour
                st.warning("⚠️ Very long audio (>1 hour). Processing may take significant time.")
            else:
                st.success(f"✅ Audio duration looks good: {duration_seconds/60:.1f} minutes")
            
            # If audio is longer than 3 minutes, use chunking (reduced threshold)
            if duration_seconds > 180:  # 3 minutes
                st.info("🔄 Large file detected - using chunking approach")
                return self._transcribe_large_file_chunked(audio_data, target_sample_rate, language_code)
            
            # For smaller files, process normally but with timeout handling
            return self._transcribe_small_file(audio_data, target_sample_rate, language_code)
            
        except Exception as e:
            st.error(f"Failed to process file: {e}")
            return None

    def _transcribe_small_file(self, audio_data, sample_rate, language_code):
        """Transcribe smaller files directly."""
        unique_filename = f"interview-audio-{uuid.uuid4()}.wav"
        try:
            # Create WAV file
            normalized_wav = BytesIO()
            sf.write(normalized_wav, audio_data, sample_rate, format='WAV')
            normalized_wav.seek(0)
            
            # Upload with retry
            gcs_uri = self._upload_to_gcs_with_retry(normalized_wav, unique_filename)
            if not gcs_uri:
                return None
            
            # Configure transcription with dynamic sample rate
            config = speech.RecognitionConfig(
                language_code=language_code,
                enable_automatic_punctuation=True,
                model="telephony",
                encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=int(sample_rate),  # Ensure integer
                audio_channel_count=1,
            )
            
            audio = speech.RecognitionAudio(uri=gcs_uri)
            
            with st.spinner("🤖 Transcribing audio..."):
                operation = self.speech_client.long_running_recognize(config=config, audio=audio)
                response = operation.result()
                
                # Extract transcript
                if response.results:
                    transcripts = [result.alternatives[0].transcript for result in response.results if result.alternatives]
                    return " ".join(transcripts)
                else:
                    st.warning("⚠️ No speech detected in audio")
                    return None
                    
        except Exception as e:
            st.error(f"Small file transcription failed: {e}")
            return None
        finally:
            # Cleanup
            try:
                bucket = self.storage_client.bucket(self.gcs_bucket_name)
                blob = bucket.blob(unique_filename)
                blob.delete()
            except:
                pass
    
    def _transcribe_large_file_chunked(self, audio_data, sample_rate, language_code):
        """Transcribe large files using parallel chunking."""
        # Use 3-minute chunks to preserve content better
        chunk_duration = 180  # seconds (balanced for quality vs speed)
        chunk_size = chunk_duration * sample_rate
        
        chunks = []
        for i in range(0, len(audio_data), chunk_size):
            chunk = audio_data[i:i + chunk_size]
            start_time = i / sample_rate
            end_time = (i + len(chunk)) / sample_rate
            
            # Create chunk buffer
            chunk_buffer = BytesIO()
            sf.write(chunk_buffer, chunk, sample_rate, format='WAV')
            chunk_buffer.seek(0)
            
            chunks.append((chunk_buffer, f"{start_time:.1f}s - {end_time:.1f}s", i // chunk_size))
        
        total_duration = len(audio_data) / sample_rate
        expected_coverage = len(chunks) * chunk_duration
        
        st.info(f"🚀 Processing {len(chunks)} chunks in parallel (3min each)")
        st.info(f"📊 Total audio: {total_duration:.1f}s")
        st.info(f"📊 Chunk coverage: {expected_coverage}s")
        
        # Validate coverage
        if expected_coverage < total_duration - 30:  # Missing more than 30s
            st.warning(f"⚠️ Potential audio loss: {total_duration - expected_coverage:.1f}s may be missing")
        else:
            st.success("✅ Full audio coverage confirmed")
        
        # Use parallel processing
        return self._transcribe_chunks_parallel(chunks, language_code)
    
    def _transcribe_chunks_parallel(self, chunks, language_code):
        """Process multiple chunks in parallel."""
        results = [None] * len(chunks)
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        def process_single_chunk(chunk_data):
            chunk_buffer, time_label, chunk_index = chunk_data
            try:
                # Upload chunk
                unique_filename = f"chunk-{uuid.uuid4()}.wav"
                gcs_uri = self._upload_to_gcs(chunk_buffer, unique_filename)
                
                # Configure transcription with proper encoding
                config = speech.RecognitionConfig(
                    language_code=language_code,
                    enable_automatic_punctuation=True,
                    model="telephony",
                    encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                )
                
                audio = speech.RecognitionAudio(uri=gcs_uri)
                operation = self.speech_client.long_running_recognize(config=config, audio=audio)
                response = operation.result()
                
                # Extract transcript
                transcript = ""
                if response.results:
                    transcript = " ".join(
                        result.alternatives[0].transcript for result in response.results
                    )
                
                # Cleanup
                try:
                    bucket = self.storage_client.bucket(self.gcs_bucket_name)
                    blob = bucket.blob(unique_filename)
                    blob.delete()
                except:
                    pass
                
                return chunk_index, transcript, time_label
                
            except Exception as e:
                return chunk_index, f"[Chunk failed: {e}]", time_label
        
        # Process chunks in parallel (max 3 concurrent)
        with ThreadPoolExecutor(max_workers=3) as executor:
            future_to_chunk = {executor.submit(process_single_chunk, chunk): chunk for chunk in chunks}
            
            completed = 0
            for future in as_completed(future_to_chunk):
                chunk_index, transcript, time_label = future.result()
                results[chunk_index] = transcript
                
                completed += 1
                progress_bar.progress(completed / len(chunks))
                
                # Show transcript preview
                preview = transcript[:100] + "..." if len(transcript) > 100 else transcript
                status_text.info(f"✅ {completed}/{len(chunks)} - {time_label}: {preview}")
        
        progress_bar.empty()
        status_text.empty()
        
        # Combine results and validate
        final_transcript = " ".join(filter(None, results))
        
        # Validation
        if len(final_transcript.strip()) < 50:  # Very short transcript
            st.warning("⚠️ Transcript seems unusually short. Check audio quality.")
        
        word_count = len(final_transcript.split())
        st.success(f"✅ Final transcript: {word_count} words, {len(final_transcript)} characters")
        
        return final_transcript
    
    def _upload_to_gcs_with_retry(self, audio_bytes, filename, max_retries=2):
        """Upload to GCS with retry logic (reduced retries for speed)."""
        for attempt in range(max_retries):
            try:
                audio_bytes.seek(0)
                return self._upload_to_gcs(audio_bytes, filename)
            except Exception as e:
                if "timeout" in str(e).lower() and attempt < max_retries - 1:
                    st.warning(f"Retry {attempt + 1}/{max_retries}...")
                    time.sleep(1)  # Reduced wait time
                    continue
                else:
                    st.error(f"Upload failed: {e}")
                    return None
        return None
    
    def _simple_noise_reduction(self, audio_data):
        """Simple noise reduction to improve transcription accuracy."""
        # Remove very quiet parts (likely noise)
        threshold = np.max(np.abs(audio_data)) * 0.02
        audio_data[np.abs(audio_data) < threshold] = 0
        return audio_data
