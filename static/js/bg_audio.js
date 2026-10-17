(() => {
    "use strict";

    const STORAGE_TIME = "cloudinator_bg_music_time";
    const STORAGE_PLAYING = "cloudinator_bg_music_playing";

    let audio = null;
    let leavingPage = false;

    function initializeAudio() {
        audio = document.getElementById("bgMusic");

        if (!audio) {
            return;
        }

        // Volume Adjustment (Decimal between 0.0 and 1.0)
        audio.volume = 0.20;

        // Restore previous playback position
        const savedTime = parseFloat(
            localStorage.getItem(STORAGE_TIME)
        );

        if (Number.isFinite(savedTime) && savedTime >= 0) {
            audio.addEventListener(
                "loadedmetadata",
                () => {
                    // Prevent seeking beyond the track duration
                    if (savedTime < audio.duration) {
                        audio.currentTime = savedTime;
                    }
                },
                { once: true }
            );
        }

        // Restore previous play state
        const wasPlaying =
            localStorage.getItem(STORAGE_PLAYING) === "true";

        // Attempt autoplay on page load
        if (wasPlaying || !localStorage.getItem(STORAGE_PLAYING)) {
            startAudio();
        }

        // Save current position
        audio.addEventListener("timeupdate", saveState);

        // Save play/pause state
        audio.addEventListener("play", () => {
            localStorage.setItem(STORAGE_PLAYING, "true");
        });

        audio.addEventListener("pause", () => {
            // Browsers can fire "pause" while a page is being torn down
            // (refresh / navigation). That is not the listener pausing, so it
            // must not turn the saved state into "not playing".
            if (leavingPage) {
                return;
            }
            localStorage.setItem(STORAGE_PLAYING, "false");
            saveState();
        });

        // Save immediately before navigating to another page
        window.addEventListener("beforeunload", () => {
            leavingPage = true;
            saveState();
        });
        window.addEventListener("pagehide", () => {
            leavingPage = true;
            saveState();
        });

        // If browser blocks autoplay, start on first user interaction
        setupInteractionFallback();
    }

    function startAudio() {
        if (!audio) {
            return;
        }

        const playPromise = audio.play();

        if (playPromise !== undefined) {
            playPromise.catch(() => {
                // Autoplay was blocked by the browser.
                // Interaction fallback will handle it.
            });
        }
    }

    function setupInteractionFallback() {
        // Browsers only allow sound after a real user gesture. Scrolling and
        // moving the mouse do NOT count, and neither does a lone Shift/Ctrl
        // key, so the first gesture may still be refused. Keep every listener
        // in place until play() has actually succeeded (the old version used
        // { once: true }, which used up the listener even when play() failed).
        const events = [
            "pointerdown",
            "mousedown",
            "click",
            "keydown",
            "touchstart",
            "touchend"
        ];

        const stopListening = () => {
            events.forEach((name) => {
                document.removeEventListener(name, startOnInteraction, true);
            });
        };

        const startOnInteraction = () => {
            if (!audio) {
                stopListening();
                return;
            }

            if (!audio.paused) {
                stopListening();
                return;
            }

            audio.play()
                .then(() => {
                    localStorage.setItem(STORAGE_PLAYING, "true");
                    stopListening();
                })
                .catch(() => {
                    // Still blocked: stay armed for the next gesture.
                });
        };

        events.forEach((name) => {
            document.addEventListener(name, startOnInteraction, true);
        });
    }

    function saveState() {
        if (!audio) {
            return;
        }

        if (Number.isFinite(audio.currentTime)) {
            localStorage.setItem(
                STORAGE_TIME,
                String(audio.currentTime)
            );
        }

        // Only record "playing" here. "Not playing" is written by the
        // explicit "pause" event above; writing it from here as well would
        // turn a browser-blocked autoplay into a saved "paused" state.
        if (!audio.paused) {
            localStorage.setItem(STORAGE_PLAYING, "true");
        }
    }

    // Initialize after DOM is ready
    if (document.readyState === "loading") {
        document.addEventListener(
            "DOMContentLoaded",
            initializeAudio
        );
    } else {
        initializeAudio();
    }
})();