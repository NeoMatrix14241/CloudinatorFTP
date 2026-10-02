(() => {
    "use strict";

    const STORAGE_TIME = "cloudinator_bg_music_time";
    const STORAGE_PLAYING = "cloudinator_bg_music_playing";

    let audio = null;

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
            localStorage.setItem(STORAGE_PLAYING, "false");
            saveState();
        });

        // Save immediately before navigating to another page
        window.addEventListener("beforeunload", saveState);

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
        const startOnInteraction = () => {
            if (!audio || !audio.paused) {
                return;
            }

            audio.play()
                .then(() => {
                    localStorage.setItem(STORAGE_PLAYING, "true");
                })
                .catch(() => {});

            document.removeEventListener(
                "click",
                startOnInteraction
            );
            document.removeEventListener(
                "keydown",
                startOnInteraction
            );
            document.removeEventListener(
                "touchstart",
                startOnInteraction
            );
        };

        document.addEventListener(
            "click",
            startOnInteraction,
            { once: true }
        );

        document.addEventListener(
            "keydown",
            startOnInteraction,
            { once: true }
        );

        document.addEventListener(
            "touchstart",
            startOnInteraction,
            { once: true }
        );
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

        localStorage.setItem(
            STORAGE_PLAYING,
            String(!audio.paused)
        );
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