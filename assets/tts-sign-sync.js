/* Let read-aloud narration and sign-language video run independently. */
(() => {
  if (window.__adtTtsSignSyncInstalled) return;
  window.__adtTtsSignSyncInstalled = true;

  const narrationAudio = (media) =>
    media instanceof HTMLAudioElement && /\/content\/i18n\/[^/]+\/audio\//.test(media.src);
  const signVideo = (media) =>
    media instanceof HTMLVideoElement && /\/content\/i18n\/[^/]+\/video\//.test(media.currentSrc || media.src);

  let manuallyPausingVideoUntil = 0;
  let signVideoDismissed = false;

  const currentVideo = () => [...document.querySelectorAll("video")].find(signVideo) ?? null;

  const positionVideo = (video) => {
    const panel = video.parentElement;
    const toolbar = document.querySelector(
      '[role="group"][aria-label="Vidhibiti vya kusoma kwa sauti"], [role="group"][aria-label="Read aloud controls"]',
    );
    if (!panel || !toolbar) return;
    const toolbarTop = toolbar.getBoundingClientRect().top;
    panel.style.setProperty("bottom", `${Math.max(16, window.innerHeight - toolbarTop + 14)}px`, "important");
    panel.style.setProperty("right", "1rem", "important");
  };

  const showSignLanguage = () => {
    if (signVideoDismissed) return;
    const toggle = [...document.querySelectorAll("button")].find((button) =>
      ["Lugha ya ishara", "Sign language"].includes(button.getAttribute("aria-label")),
    );
    if (toggle && toggle.getAttribute("aria-pressed") !== "true") toggle.click();
  };

  // The reader runtime treats TTS and sign language as competing media. Keep
  // the video's native play event away from that handler, so video playback
  // cannot stop narration.
  document.addEventListener("play", (event) => {
    if (!signVideo(event.target)) return;
    positionVideo(event.target);
    event.stopPropagation();
  }, true);

  // TTS internally marks itself as the active medium, then pauses the video.
  // Reverse only that programmatic pause; a pause from video controls remains
  // the learner's choice, so either medium can run alone.
  document.addEventListener("pause", (event) => {
    const video = event.target;
    if (!signVideo(video) || video.ended || performance.now() < manuallyPausingVideoUntil) return;
    window.setTimeout(() => {
      if (video.paused && performance.now() >= manuallyPausingVideoUntil) {
        void video.play().catch(() => {});
      }
    }, 0);
  }, true);

  document.addEventListener("pointerdown", (event) => {
    if (event.target instanceof Element && event.target.closest("video")) {
      manuallyPausingVideoUntil = performance.now() + 750;
    }
  }, true);

  document.addEventListener("click", (event) => {
    const button = event.target.closest?.("button");
    if (!button) return;
    const label = button.getAttribute("aria-label");
    if (["Lugha ya ishara", "Sign language"].includes(label)) {
      signVideoDismissed = button.getAttribute("aria-pressed") === "true";
    }
    if (["Funga", "Close"].includes(label) && currentVideo()?.parentElement?.contains(button)) {
      signVideoDismissed = true;
    }
  }, true);

  const nativePlay = HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play = function (...args) {
    if (narrationAudio(this)) {
      // Show the matching signer when narration begins, but do not start or
      // pause the video. The learner controls each medium independently.
      window.setTimeout(showSignLanguage, 0);
      window.setTimeout(() => {
        const video = currentVideo();
        if (video) positionVideo(video);
      }, 100);
    }
    return nativePlay.apply(this, args);
  };

  window.addEventListener("resize", () => {
    const video = currentVideo();
    if (video) positionVideo(video);
  });
})();
