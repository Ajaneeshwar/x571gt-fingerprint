#!/usr/bin/env python3
"""Re-apply the X571GT press-mode + SIGFM changes to a fresh sigfm-branch clone."""
import sys, pathlib

root = pathlib.Path(__file__).parent / "libfprint-sigfm"
edits = []

def edit(path, old, new):
    edits.append((path, old, new))

# 1. elanspi.h: add touchpad PID 04f3:3104
edit("libfprint/drivers/elanspi.h",
     '  {.udev_types = ELANSPI_UDEV_TYPES, .spi_acpi_id = "ELAN7001", .hid_id = {.vid = ELANSPI_TP_VID, .pid = 0x3057}, .driver_data = ELANSPI_180_ROTATE},',
     '  {.udev_types = ELANSPI_UDEV_TYPES, .spi_acpi_id = "ELAN7001", .hid_id = {.vid = ELANSPI_TP_VID, .pid = 0x3104}, .driver_data = ELANSPI_NO_ROTATE},\n'
     '  {.udev_types = ELANSPI_UDEV_TYPES, .spi_acpi_id = "ELAN7001", .hid_id = {.vid = ELANSPI_TP_VID, .pid = 0x3057}, .driver_data = ELANSPI_180_ROTATE},')

# 2. struct fields
edit("libfprint/drivers/elanspi.c",
     "  gint     fp_empty_counter;\n  GSList  *fp_frame_list;",
     "  gint     fp_empty_counter;\n  GSList  *fp_frame_list;\n\n"
     "  /* press-mode capture (eFSA80SC + SIGFM) */\n"
     "  guint8  *press_frame;\n  gint     press_frame_count;\n  gint     bg_poison_counter;")

# 3. buffer allocation
edit("libfprint/drivers/elanspi.c",
     "      self->last_image = g_malloc0 (self->sensor_width * self->sensor_height * 2);\n"
     "      self->bg_image = g_malloc0 (self->sensor_width * self->sensor_height * 2);\n"
     "      self->prev_frame_image = g_malloc0 (self->sensor_width * self->sensor_height * 2);",
     "      self->last_image = g_malloc0 (self->sensor_width * self->sensor_height * 2);\n"
     "      self->bg_image = g_malloc0 (self->sensor_width * self->sensor_height * 2);\n"
     "      self->prev_frame_image = g_malloc0 (self->sensor_width * self->sensor_height * 2);\n"
     "      g_clear_pointer (&self->press_frame, g_free);\n"
     "      self->press_frame = g_malloc0 (self->sensor_width * self->sensor_height);")

# 4. press-mode processing + submit functions
edit("libfprint/drivers/elanspi.c",
     "static unsigned char\n"
     "elanspi_fp_assembling_get_pixel (struct fpi_frame_asmbl_ctx *ctx, struct fpi_frame *frame, unsigned int x, unsigned int y)\n"
     "{\n"
     "  return frame->data[y * ctx->frame_width + x];\n"
     "}",
     "static unsigned char\n"
     "elanspi_fp_assembling_get_pixel (struct fpi_frame_asmbl_ctx *ctx, struct fpi_frame *frame, unsigned int x, unsigned int y)\n"
     "{\n"
     "  return frame->data[y * ctx->frame_width + x];\n"
     "}\n"
     "\n"
     "/* Press-mode capture for the eFSA80SC: the swipe/stitch pipeline produces\n"
     " * speed-distorted strips that NBIS cannot match (genuine pairs score ~0),\n"
     " * while single full 80x80 frames match reliably with SIGFM. Tone-map the\n"
     " * whole frame (no rotation - SIGFM is rotation invariant, and no crop). */\n"
     "static void\n"
     "elanspi_process_press_frame (FpiDeviceElanSpi *self, const guint16 *data_in, guint8 *data_out)\n"
     "{\n"
     "  size_t frame_size = (size_t) self->sensor_width * self->sensor_height;\n"
     "  g_autofree guint16 *sorted = g_memdup2 (data_in, frame_size * 2);\n"
     "\n"
     "  qsort (sorted, frame_size, 2, cmp_u16);\n"
     "  guint16 lvl0 = sorted[0];\n"
     "  guint16 lvl1 = sorted[frame_size * 3 / 10];\n"
     "  guint16 lvl2 = sorted[frame_size * 65 / 100];\n"
     "  guint16 lvl3 = sorted[frame_size - 1];\n"
     "\n"
     "  lvl1 = MAX (lvl1, lvl0 + 1);\n"
     "  lvl2 = MAX (lvl2, lvl1 + 1);\n"
     "  lvl3 = MAX (lvl3, lvl2 + 1);\n"
     "\n"
     "  for (size_t i = 0; i < frame_size; i++)\n"
     "    {\n"
     "      guint16 px = data_in[i];\n"
     "      if (px < lvl0)\n"
     "        px = 0;\n"
     "      else if (px > lvl3)\n"
     "        px = 255;\n"
     "      else if (px < lvl1)\n"
     "        px = (px - lvl0) * 99 / (lvl1 - lvl0);\n"
     "      else if (px < lvl2)\n"
     "        px = 99 + ((px - lvl1) * 56 / (lvl2 - lvl1));\n"
     "      else\n"
     "        px = 155 + ((px - lvl2) * 100 / (lvl3 - lvl2));\n"
     "      data_out[i] = px;\n"
     "    }\n"
     "}\n"
     "\n"
     "#define ELANSPI_PRESS_FRAMES 10\n"
     "\n"
     "static void\n"
     "elanspi_fp_submit_press_frame (FpiDeviceElanSpi *self)\n"
     "{\n"
     "  FpImage *img = fp_image_new (self->sensor_width, self->sensor_height);\n"
     "\n"
     "  memcpy (img->data, self->press_frame,\n"
     "          (size_t) self->sensor_width * self->sensor_height);\n"
     "  img->flags |= FPI_IMAGE_PARTIAL | FPI_IMAGE_COLORS_INVERTED;\n"
     "\n"
     "  fpi_image_device_image_captured (FP_IMAGE_DEVICE (self), img);\n"
     "  self->press_frame_count = 0;\n"
     "}")

# 5. frame handler press branch
edit("libfprint/drivers/elanspi.c",
     "  switch (elanspi_guess_image (self, self->last_image))\n"
     "    {\n"
     "    case ELANSPI_GUESS_UNKNOWN:\n"
     "      fp_dbg (\"<fp_frame> unknown, ignore...\");\n"
     "      break;\n"
     "\n"
     "    case ELANSPI_GUESS_EMPTY:\n"
     "      self->fp_empty_counter += 1;",
     "  /* press-mode path: collect a stable full frame, no stitching */\n"
     "  if (self->sensor_id == 0xe)\n"
     "    {\n"
     "      switch (elanspi_guess_image (self, self->last_image))\n"
     "        {\n"
     "        case ELANSPI_GUESS_UNKNOWN:\n"
     "          fp_dbg (\"<press> unknown, ignore...\");\n"
     "          break;\n"
     "\n"
     "        case ELANSPI_GUESS_EMPTY:\n"
     "          self->fp_empty_counter += 1;\n"
     "          if (self->fp_empty_counter > 1)\n"
     "            {\n"
     "              if (self->press_frame_count >= 3)\n"
     "                {\n"
     "                  fp_dbg (\"<press> finger lifted with usable frame, submitting\");\n"
     "                  elanspi_fp_submit_press_frame (self);\n"
     "                }\n"
     "              else\n"
     "                {\n"
     "                  fp_dbg (\"<press> finger lifted too early\");\n"
     "                  self->press_frame_count = 0;\n"
     "                  fpi_image_device_retry_scan (FP_IMAGE_DEVICE (self), FP_DEVICE_RETRY_TOO_SHORT);\n"
     "                }\n"
     "              goto finish_capture;\n"
     "            }\n"
     "          break;\n"
     "\n"
     "        case ELANSPI_GUESS_FINGERPRINT:\n"
     "          self->fp_empty_counter = 0;\n"
     "          elanspi_correct_with_bg (self, self->last_image);\n"
     "          elanspi_process_press_frame (self, self->last_image, self->press_frame);\n"
     "          self->press_frame_count += 1;\n"
     "          if (self->press_frame_count >= ELANSPI_PRESS_FRAMES)\n"
     "            {\n"
     "              fp_dbg (\"<press> have stable frame, submitting\");\n"
     "              elanspi_fp_submit_press_frame (self);\n"
     "              goto finish_capture;\n"
     "            }\n"
     "          break;\n"
     "        }\n"
     "\n"
     "      fpi_ssm_jump_to_state_delayed (ssm, ELANSPI_FPCAPT_FP_CAPTURE, ELANSPI_HV_SENSOR_FRAME_DELAY);\n"
     "      return;\n"
     "    }\n"
     "\n"
     "  switch (elanspi_guess_image (self, self->last_image))\n"
     "    {\n"
     "    case ELANSPI_GUESS_UNKNOWN:\n"
     "      fp_dbg (\"<fp_frame> unknown, ignore...\");\n"
     "      break;\n"
     "\n"
     "    case ELANSPI_GUESS_EMPTY:\n"
     "      self->fp_empty_counter += 1;")

# 6. reset press counter at capture start
edit("libfprint/drivers/elanspi.c",
     "      /* prepare to take actual image */\n"
     "      self->finger_wait_debounce = 0;\n"
     "      g_slist_free_full (g_steal_pointer (&self->fp_frame_list), g_free);\n"
     "      self->fp_empty_counter = 0;",
     "      /* prepare to take actual image */\n"
     "      self->finger_wait_debounce = 0;\n"
     "      g_slist_free_full (g_steal_pointer (&self->fp_frame_list), g_free);\n"
     "      self->fp_empty_counter = 0;\n"
     "      self->press_frame_count = 0;")

# 7. class init: SIGFM algorithm + threshold
edit("libfprint/drivers/elanspi.c",
     "  img_class->bz3_threshold = 24;\n  img_class->img_open = elanspi_open;",
     "  /* SIGFM (SIFT) matching: press-mode 80x80 frames from the eFSA80SC are\n"
     "   * far too distortion-varied for NBIS but match cleanly with SIGFM.\n"
     "   * Threshold from measured data: genuine presses score 16-24 inliers,\n"
     "   * impostor/mirror controls score ~1. */\n"
     "  img_class->algorithm = FPI_DEVICE_ALGO_SIGFM;\n"
     "  img_class->bz3_threshold = 8;\n"
     "  img_class->img_open = elanspi_open;")

# 8. finalize: free press frame
edit("libfprint/drivers/elanspi.c",
     "  g_clear_pointer (&self->prev_frame_image, g_free);\n"
     "  g_slist_free_full (g_steal_pointer (&self->fp_frame_list), g_free);",
     "  g_clear_pointer (&self->prev_frame_image, g_free);\n"
     "  g_clear_pointer (&self->press_frame, g_free);\n"
     "  g_slist_free_full (g_steal_pointer (&self->fp_frame_list), g_free);")

# 9. background self-healing in guess_image
edit("libfprint/drivers/elanspi.c",
     '  fp_dbg ("<guess> stddev=%" G_GUINT64_FORMAT "d, ip=%d, is_fp=%d, is_empty=%d", sq_stddev, invalid_percent, is_fp, is_empty);',
     '  fp_dbg ("<guess> stddev=%" G_GUINT64_FORMAT "d, ip=%d, is_fp=%d, is_empty=%d", sq_stddev, invalid_percent, is_fp, is_empty);\n'
     "\n"
     "  /* A background captured while a finger rested on the sensor blinds every\n"
     "   * later frame: the whole image clamps below bg (ip ~100, stddev ~0).\n"
     "   * Heal by re-learning the background from the current raw frame. */\n"
     "  if (invalid_percent >= 98 && sq_stddev <= 2)\n"
     "    {\n"
     "      self->bg_poison_counter += 1;\n"
     "      if (self->bg_poison_counter >= 10)\n"
     "        {\n"
     "          fp_dbg (\"<guess> background looks poisoned, re-learning from current frame\");\n"
     "          memcpy (self->bg_image, raw_image, self->sensor_height * self->sensor_width * 2);\n"
     "          self->bg_poison_counter = 0;\n"
     "        }\n"
     "    }\n"
     "  else\n"
     "    {\n"
     "      self->bg_poison_counter = 0;\n"
     "    }")

# 10. sigfm meson: opencv5 fallback + optional doctest
edit("libfprint/sigfm/meson.build",
     "opencv = dependency('opencv4', required: true, version: '>=4.5.0')\n"
     "doctest = dependency('doctest', required: true, version: ['>=2.0.0', '<3.0.0'])\n"
     "\n"
     "libsigfm = static_library('sigfm',\n"
     "        sigfm_sources,\n"
     "        dependencies: [opencv],\n"
     ")\n"
     "sigfm_tests = executable('sigfm-tests', ['./tests.cpp'], dependencies: [doctest, opencv], link_with: [libsigfm])",
     "opencv = dependency('opencv5', required: false, version: '>=5.0.0')\n"
     "if not opencv.found()\n"
     "    opencv = dependency('opencv4', required: true, version: '>=4.5.0')\n"
     "endif\n"
     "doctest = dependency('doctest', required: false, version: ['>=2.0.0', '<3.0.0'])\n"
     "\n"
     "libsigfm = static_library('sigfm',\n"
     "        sigfm_sources,\n"
     "        dependencies: [opencv],\n"
     ")\n"
     "if doctest.found()\n"
     "    sigfm_tests = executable('sigfm-tests', ['./tests.cpp'], dependencies: [doctest, opencv], link_with: [libsigfm])\n"
     "endif")

fails = 0
for path, old, new in edits:
    p = root / path
    text = p.read_text()
    if old not in text:
        print(f"FAIL: pattern not found in {path}: {old[:60]!r}...")
        fails += 1
        continue
    p.write_text(text.replace(old, new, 1))
    print(f"ok: {path}: {old[:50]!r}...")
sys.exit(1 if fails else 0)
