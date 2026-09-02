# Legacy: the NBIS-era patch (superseded)

`elanspi-x571gt.patch` (on libfprint v1.94.100) was the first working-capture
attempt, keeping the stock swipe-stitch + bozorth3 architecture:

- adds touchpad PID `04f3:3104` with `ELANSPI_90RIGHT_ROTATE` (the sensor is
  mounted 90° rotated in the touchpad — matters for stitching, irrelevant for
  the SIGFM press-mode approach);
- unsharp mask after the 2x resize (raised minutiae counts from ~5 to ~25);
- horizontal drift clamp in frame assembly (removed per-swipe shear and fake
  seam minutiae);
- a meson dict-foreach fix for newer meson in tests/meson.build.

Capture quality became good, but genuine bozorth3 scores topped out at 10 of
the required 24 because swipe-speed distortion varies within every swipe (see
the main README). Kept because these fixes are what you would upstream to
mainline libfprint's swipe pipeline for this hardware.
