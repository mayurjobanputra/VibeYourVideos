# Implementation Plan: OpenStoryMode

## Overview

Incremental implementation of the OpenStoryMode video generation pipeline. We start with data models and configuration, build each pipeline component (script processor, visual generator, TTS engine, video assembler), wire them together via the pipeline manager and REST API, then build the web frontend. Each step builds on the previous and ends with full integration.

## Tasks

- [ ] 1. Set up project structure, data models, and configuration
  - [x] 1.1 Create project directory structure and install dependencies
    - Create `app/` package with `__init__.py`, `models.py`, `config.py`, `main.py`
    - Create `tests/` directory with `__init__.py`
    - Create `static/` directory for frontend files
    - Create `requirements.txt` with: `fastapi`, `uvicorn`, `httpx`, `ffmpeg-python`, `hypothesis`, `pytest`, `python-dotenv`
    - _Requirements: 9.1, 9.2_

  - [x] 1.2 Implement data models in `app/models.py`
    - Implement `VideoLength`, `AspectRatio`, `JobStage` enums with helper methods (`to_seconds()`, `resolution()`)
    - Implement `Scene`, `SceneAsset`, `GenerationRequest`, `Job` dataclasses as defined in the design
    - _Requirements: 1.3, 1.4, 2.1_

  - [x] 1.3 Implement configuration loading in `app/config.py`
    - Read `OPENROUTER_API_KEY` and `PORT` (default 8000) from environment variables or `.env` file
    - Implement startup validation that raises an error with a specific message if the API key is missing
    - _Requirements: 9.3, 9.4_

  - [ ]* 1.4 Write property tests for data models and configuration
    - **Property 7: Aspect ratio determines resolution** — For any `AspectRatio` value, `resolution()` returns the correct mapping (9:16 → 720×1280, 16:9 → 1280×720)
    - **Validates: Requirements 3.2**
    - **Property 18: Configuration reading and validation** — For any config where the API key is set/unset, the system reads it back correctly or reports it missing
    - **Validates: Requirements 9.3, 9.4**

- [ ] 2. Implement prompt validation and generation request handling
  - [x] 2.1 Implement prompt validation logic in `app/validation.py`
    - Reject empty or whitespace-only prompts
    - Enforce max 5000 character limit
    - Validate `video_length` and `aspect_ratio` against allowed enum values
    - Return structured validation errors
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

  - [ ]* 2.2 Write property tests for prompt validation
    - **Property 1: Empty/whitespace prompt rejection** — For any whitespace-only string, validation rejects it
    - **Validates: Requirements 1.2**
    - **Property 2: Valid prompt acceptance** — For any non-empty, non-whitespace string ≤5000 chars with valid length/ratio, validation accepts it
    - **Validates: Requirements 1.5**

- [ ] 3. Implement OpenRouter API client with retry logic
  - [x] 3.1 Create `app/openrouter.py` with a unified API client
    - Implement async HTTP client using `httpx` for calling OpenRouter endpoints
    - Implement retry wrapper: up to 2 retries with exponential backoff (1s, 2s delays)
    - Support three call types: LLM completion, image generation, TTS synthesis
    - Include scene identifier and error details in failure reports
    - _Requirements: 3.3, 3.4, 4.3, 4.4_

  - [ ]* 3.2 Write property tests for retry logic
    - **Property 8: API retry on failure** — For any sequence of API failures, the system retries up to 2 additional times (3 total) before reporting error with scene ID and details
    - **Validates: Requirements 3.3, 3.4, 4.3, 4.4**

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 5. Implement Script Processor
  - [x] 5.1 Create `app/script_processor.py`
    - Build LLM prompt template that instructs the model to produce JSON with scene breakdowns (narration_text + visual_description per scene)
    - Determine scene count based on video length (roughly 1 scene per 5-10 seconds)
    - Parse and validate LLM JSON response against expected schema
    - Return `list[Scene]` on success, propagate error within 10 seconds on LLM failure
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [ ]* 5.2 Write property tests for script processor
    - **Property 3: Script structure validity** — For any valid request, output is a non-empty list of Scenes each with non-empty narration_text and visual_description
    - **Validates: Requirements 2.1**
    - **Property 4: Scene count scales with video length** — For any pair of video lengths, longer length produces ≥ scenes than shorter
    - **Validates: Requirements 2.2**
    - **Property 5: Narration duration within tolerance** — For any generated script, estimated spoken duration is within ±20% of target video length
    - **Validates: Requirements 2.4**

- [ ] 6. Implement Visual Generator and TTS Engine
  - [x] 6.1 Create `app/visual_generator.py`
    - Call OpenRouter image generation endpoint with scene visual_description
    - Map aspect ratio to resolution (9:16 → 720×1280, 16:9 → 1280×720)
    - Save generated image to `output/{job_id}/scenes/scene_{index}_image.png`
    - Use retry wrapper from `openrouter.py`; report failure with scene identifier on exhaustion
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

  - [x] 6.2 Create `app/tts_engine.py`
    - Call OpenRouter TTS endpoint with scene narration_text
    - Save audio output as MP3 to `output/{job_id}/scenes/scene_{index}_audio.mp3`
    - Use retry wrapper from `openrouter.py`; report failure with scene identifier on exhaustion
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

  - [ ]* 6.3 Write property tests for generators
    - **Property 6: One asset per scene** — For any list of scenes, visual generator produces exactly one image per scene and TTS produces exactly one audio per scene
    - **Validates: Requirements 3.1, 4.1**
    - **Property 9: TTS audio format compatibility** — For any TTS output, the file is WAV or MP3 format
    - **Validates: Requirements 4.2**

- [ ] 7. Implement Video Assembler
  - [x] 7.1 Create `app/video_assembler.py`
    - Build FFmpeg command to composite scene images + audio into a single MP4
    - Each visual displays for the duration of its corresponding narration audio
    - Apply 0.5s crossfade transition between consecutive scenes
    - Render at the user-selected aspect ratio resolution
    - Save output to `output/{job_id}/output.mp4`
    - Capture FFmpeg stderr on failure and include in error report
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [ ]* 7.2 Write property tests for video assembler
    - **Property 10: Video assembly produces valid MP4** — For any complete set of SceneAssets, assembler produces a single MP4 file
    - **Validates: Requirements 5.1**
    - **Property 11: Output video matches selected aspect ratio** — For any assembled video, dimensions match the selected ratio
    - **Validates: Requirements 5.2**
    - **Property 12: Visual-audio synchronization** — For any scene, visual duration equals audio duration within ±0.1s
    - **Validates: Requirements 5.3**

- [x] 8. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 9. Implement Pipeline Manager
  - [x] 9.1 Create `app/pipeline.py`
    - Implement `run_pipeline(job: Job)` that orchestrates: script generation → concurrent visual + TTS per scene → video assembly
    - Use `asyncio.gather` to run visual generation and TTS synthesis concurrently for each scene
    - Track job stage transitions: QUEUED → SCRIPT_GENERATION → VISUAL_GENERATION/TTS_SYNTHESIS → VIDEO_ASSEMBLY → COMPLETE
    - Abort pipeline and set ERROR stage if any scene fails both visual and TTS after retries
    - Store script JSON to `output/{job_id}/script.json`
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

  - [ ]* 9.2 Write property tests for pipeline
    - **Property 14: Job status reflects stage and errors** — For any Job, status includes valid stage; ERROR stage includes non-empty error message and error_stage
    - **Validates: Requirements 7.1, 7.3**
    - **Property 15: Pipeline stage ordering** — For any successful job, stages follow QUEUED → SCRIPT_GENERATION → VISUAL_GENERATION/TTS_SYNTHESIS → VIDEO_ASSEMBLY → COMPLETE
    - **Validates: Requirements 8.2**
    - **Property 16: Pipeline abort on scene failure** — For any scene failing both visual and TTS after retries, pipeline transitions to ERROR and does not proceed to assembly
    - **Validates: Requirements 8.3**
    - **Property 17: Artifact storage completeness** — For any completed job, output directory contains script.json, one image per scene, one audio per scene, and output.mp4
    - **Validates: Requirements 8.4**

- [ ] 10. Implement REST API endpoints and static file serving
  - [x] 10.1 Implement FastAPI app in `app/main.py`
    - `POST /api/generate`: Validate request, create Job, launch pipeline as background task, return 202 with job_id
    - `GET /api/status/{job_id}`: Return job status including stage, progress, error, and video_url when complete
    - `GET /api/video/{job_id}`: Stream the MP4 file from the output directory
    - `GET /`: Serve static HTML/JS/CSS from `static/` directory
    - Configure server port from config (default 8000)
    - Validate OpenRouter API key on startup
    - _Requirements: 1.5, 6.1, 6.2, 6.3, 7.1, 7.2, 7.3, 9.1, 9.2, 9.3_

  - [x] 10.2 Implement video metadata extraction utility
    - Extract duration, aspect ratio, and file size from the generated MP4 using FFmpeg probe
    - Return metadata in the status response when job is complete
    - _Requirements: 6.3_

  - [ ]* 10.3 Write property test for video metadata
    - **Property 13: Video metadata completeness** — For any completed video, metadata returns non-null positive values for duration, aspect ratio, and file size
    - **Validates: Requirements 6.3**

- [ ] 11. Implement Web UI frontend
  - [x] 11.1 Create `static/index.html` with inline JS and CSS
    - Prompt textarea with character counter (max 5000 chars)
    - Video length dropdown (10s, 30s, 60s, 90s)
    - Aspect ratio dropdown (9:16 vertical, 16:9 horizontal)
    - Submit button with client-side validation (reject empty/whitespace prompts)
    - Progress display area showing current stage name, polling `/api/status/{job_id}` every 3-5 seconds
    - Inline `<video>` player shown on completion with download button
    - Metadata display: duration, aspect ratio, file size
    - Error display: error message and failure stage
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 6.1, 6.2, 6.3, 7.1, 7.2, 7.3_

- [x] 12. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- All external AI calls route through OpenRouter via a single API key
- Python with FastAPI is the implementation language throughout
