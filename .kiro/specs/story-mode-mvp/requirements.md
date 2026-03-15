# Requirements Document

## Introduction

OpenStoryMode is a local-first application that generates short-form animated videos from a text prompt. The user provides a script via a web interface, selects a target video length and aspect ratio, and the system produces a multi-scene video with AI-generated visuals and TTS narration. The application runs as a localhost daemon with a Python backend and a simple web frontend, calling external AI APIs via OpenRouter (a unified API gateway) for LLM script generation, image generation, and text-to-speech.

## Glossary

- **Web_UI**: The browser-based frontend served on localhost that provides the user interface for prompt input, configuration, and video playback.
- **Backend**: The Python API server (built with FastAPI) that orchestrates script processing, scene generation, TTS synthesis, and video assembly.
- **OpenRouter**: A unified API gateway (https://openrouter.ai/) used for all external AI calls — LLM script generation, image generation, and TTS synthesis — via a single API key.
- **Script_Processor**: The component within the Backend that takes a user prompt and breaks it into a structured scene-by-scene script using an LLM via OpenRouter.
- **Scene**: A single segment of the video consisting of one visual (AI-generated image or video clip) paired with its corresponding narration audio.
- **Visual_Generator**: The component that calls OpenRouter's image generation endpoint to produce visuals for each Scene.
- **TTS_Engine**: The component that calls OpenRouter's text-to-speech endpoint to synthesize narration audio from script text.
- **Video_Assembler**: The component that composites Scene visuals and narration audio into a final rendered video file.
- **Aspect_Ratio**: The width-to-height ratio of the output video. Supported values are 9:16 (vertical) and 16:9 (horizontal).
- **Video_Length**: The target duration of the output video. Supported values are 10s, 30s, 60s, and 90s.

## Requirements

### Requirement 1: Prompt Input

**User Story:** As a user, I want to enter a text prompt describing my video idea, so that the system can generate a video from it.

#### Acceptance Criteria

1. THE Web_UI SHALL display a text input area where the user can enter a prompt of up to 5000 characters.
2. WHEN the user submits an empty prompt, THE Web_UI SHALL display a validation error and prevent submission.
3. THE Web_UI SHALL display a dropdown for selecting Video_Length with options: 10s, 30s, 60s, 90s.
4. THE Web_UI SHALL display a dropdown for selecting Aspect_Ratio with options: 9:16 (vertical), 16:9 (horizontal).
5. WHEN the user submits a valid prompt with selected Video_Length and Aspect_Ratio, THE Web_UI SHALL send the request to the Backend and display a progress indicator.

### Requirement 2: Script Generation

**User Story:** As a user, I want the system to automatically break my prompt into a scene-by-scene script, so that each scene has clear narration and visual direction.

#### Acceptance Criteria

1. WHEN the Backend receives a valid prompt, THE Script_Processor SHALL generate a structured script containing one or more Scenes, each with narration text and a visual description.
2. THE Script_Processor SHALL determine the number of Scenes based on the selected Video_Length, distributing narration evenly across the target duration.
3. WHEN the LLM API call fails, THE Script_Processor SHALL return an error message to the Web_UI within 10 seconds.
4. THE Script_Processor SHALL produce Scene narration text that, when spoken, fits within the selected Video_Length tolerance of plus or minus 20 percent.

### Requirement 3: Visual Generation

**User Story:** As a user, I want each scene to have an AI-generated visual, so that the video has compelling imagery matching the narration.

#### Acceptance Criteria

1. WHEN a Scene script is ready, THE Visual_Generator SHALL call OpenRouter's image generation endpoint to produce one visual per Scene.
2. THE Visual_Generator SHALL generate visuals at a resolution appropriate for the selected Aspect_Ratio (minimum 720p equivalent).
3. WHEN the image generation API call fails for a Scene, THE Visual_Generator SHALL retry the request up to 2 times before reporting an error.
4. IF all retries fail for a Scene, THEN THE Visual_Generator SHALL report the failure to the Backend with the Scene identifier and error details.

### Requirement 4: TTS Narration

**User Story:** As a user, I want the system to convert my script into spoken narration, so that the video has a professional voiceover.

#### Acceptance Criteria

1. WHEN a Scene script is ready, THE TTS_Engine SHALL synthesize narration audio from the Scene narration text using OpenRouter's TTS endpoint.
2. THE TTS_Engine SHALL produce audio in a format compatible with the Video_Assembler (WAV or MP3).
3. WHEN the TTS API call fails for a Scene, THE TTS_Engine SHALL retry the request up to 2 times before reporting an error.
4. IF all retries fail for a Scene, THEN THE TTS_Engine SHALL report the failure to the Backend with the Scene identifier and error details.

### Requirement 5: Video Assembly

**User Story:** As a user, I want the system to combine visuals and narration into a single video file, so that I get a ready-to-use output.

#### Acceptance Criteria

1. WHEN all Scenes have both a visual and narration audio, THE Video_Assembler SHALL composite them into a single video file in MP4 format.
2. THE Video_Assembler SHALL render the video at the user-selected Aspect_Ratio.
3. THE Video_Assembler SHALL synchronize each Scene visual with its corresponding narration audio so that the visual displays for the duration of the narration.
4. THE Video_Assembler SHALL apply a crossfade transition of 0.5 seconds between consecutive Scenes.
5. WHEN the video assembly process fails, THE Video_Assembler SHALL report the error to the Backend with details of the failure point.

### Requirement 6: Video Output and Playback

**User Story:** As a user, I want to preview and download the generated video, so that I can review it and use it on social platforms.

#### Acceptance Criteria

1. WHEN video assembly completes, THE Web_UI SHALL display an inline video player for previewing the generated video.
2. THE Web_UI SHALL provide a download button that saves the MP4 file to the user's local filesystem.
3. THE Web_UI SHALL display the video metadata including duration, Aspect_Ratio, and file size.

### Requirement 7: Generation Progress Tracking

**User Story:** As a user, I want to see the progress of my video generation, so that I know how long to wait and what stage the system is at.

#### Acceptance Criteria

1. WHILE the Backend is processing a video generation request, THE Web_UI SHALL display the current processing stage (script generation, visual generation, TTS synthesis, video assembly).
2. WHILE the Backend is processing, THE Web_UI SHALL update the progress indicator at intervals of no more than 5 seconds.
3. WHEN an error occurs during any processing stage, THE Web_UI SHALL display the error message and the stage at which the failure occurred.

### Requirement 8: Pipeline Orchestration

**User Story:** As a user, I want the generation pipeline to run efficiently, so that I get my video as fast as possible.

#### Acceptance Criteria

1. THE Backend SHALL process visual generation and TTS synthesis for independent Scenes concurrently.
2. THE Backend SHALL execute the pipeline stages in order: script generation, then concurrent visual and TTS generation, then video assembly.
3. IF any Scene fails both visual generation and TTS generation after retries, THEN THE Backend SHALL abort the pipeline and report the error to the Web_UI.
4. THE Backend SHALL store generated artifacts (script, visuals, audio, final video) in a local output directory.

### Requirement 9: Local Server Operation

**User Story:** As a user, I want to run the application locally, so that I can test and iterate without deploying to a remote server.

#### Acceptance Criteria

1. THE Backend SHALL run as a localhost HTTP server on a configurable port (default 8000).
2. THE Backend SHALL serve the Web_UI static files and expose a REST API for video generation.
3. WHEN the Backend starts, THE Backend SHALL validate that the required OpenRouter API key is configured and report if it is missing.
4. THE Backend SHALL read the OpenRouter API key and configuration from environment variables or a local configuration file.
