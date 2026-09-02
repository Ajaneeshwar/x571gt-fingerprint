# Fingerprint login for the ASUS VivoBook X571GT on Linux

**Status: fully working.** `fprintd` enroll + verify, PAM integration for
sudo, polkit, and the lock screen. Tested on Arch Linux (Omarchy), kernel 7.1,
libfprint 1.94.x, September 2026.

This repo contains everything needed to make the X571GT's fingerprint reader
work on Linux: a patched `libfprint` package, the patch itself, build scripts,
and, most importantly, the full story of *why* this sensor never worked
before. Three independent problems had to be solved, and each one on its
own looks like a dead end.

## The hardware

The X571GT's reader is invisible to `lsusb`, which makes most guides conclude
"no sensor present". It is real, but it lives on SPI:

| Property | Value |
|---|---|
| ACPI ID | `ELAN7001` (`/sys/bus/spi/devices/spi-ELAN7001:00`) |
| Sensor die | ElanTech `eFSA80SC` (id `0xe`), 80x80 px |
| Companion touchpad HID | `04f3:3104` (`ELAN1200`) |
| Device nodes | `/dev/spidev1.0` + `/dev/hidraw0` |

Other laptops with the same die: ASUS VivoBook S13 S330FA, ExpertBook P2451FA.
If you landed here searching for `ELAN7001`, `elanspi`, `04f3:3104`,
`fprintd` "no devices available", or `lsusb` showing no fingerprint reader
on a VivoBook/ExpertBook: this is the same problem, and this repo fixes it.

## The three problems (and fixes)

### 1. `spidev.bufsiz`: "sensor captures one frame, then dies"

The kernel's default SPI userspace buffer is 4096 bytes. This sensor's frames
need transfers of ~16 KB, so every capture silently truncates and the sensor
appears to lock up after a single frame. The fix is one config file
([`elan-spidev.conf`](elan-spidev.conf)):

```
# /etc/modprobe.d/elan-spidev.conf
options spidev bufsiz=32768
```

Reload with `modprobe -r spidev && modprobe spidev` (or reboot). Without this,
*nothing else in this repo works*. Credit: discovered for the same die in
[mincrmatt12/elan-spi-fingerprint#3](https://github.com/mincrmatt12/elan-spi-fingerprint/issues/3).

### 2. Missing device ID

Mainline libfprint's `elanspi` driver has never listed touchpad PID
`04f3:3104`, so the driver never claims the device. One table entry in
`drivers/elanspi.h` fixes detection.

### 3. The matcher: the real wall

This is why the sensor stayed broken for years even for people who got
capture working. The stock driver treats the 80x80 die as a *swipe* sensor:
it films ~100 frames while you drag your finger and stitches them into a
strip. But the stitched strip's geometry depends on your swipe speed, which
varies *within* every swipe, so every capture of the same finger is warped
differently. libfprint's only stock matcher (NIST bozorth3, minutiae
distance based) is not distortion-tolerant. Measured with an offline bz3
harness on real captures:

| comparison | bozorth3 score (threshold 24) |
|---|---|
| a capture vs. itself | 100-150 |
| the same capture stretched 20% vertically | 0-4 |
| two genuine consecutive swipes, best case | 0-10 |

Genuine pairs can never reach the threshold; lowering the threshold into the
0-10 range would false-accept. **No amount of image cleanup fixes this.** We
tried rotation correction (the sensor is mounted 90° in the touchpad), unsharp
masking, drift clamping, and ridge-frequency normalization. Each improved
the images; none moved the genuine score above 10.

The fix is to change the architecture, not tune it:

- **Press mode instead of swipe mode.** The die delivers full 2-D 80x80
  frames, so treat it like a small touch sensor: capture one stable
  tone-mapped frame per finger press. No stitching, no distortion.
- **SIGFM instead of bozorth3.** [SIGFM](https://github.com/goodix-fp-linux-dev/sigfm)
  is a SIFT-keypoint matcher built by the Goodix-on-Linux community exactly
  for tiny low-res sensors (64x80), with an existing libfprint integration on
  the [`sigfm` branch](https://github.com/goodix-fp-linux-dev/libfprint/tree/sigfm).
  Local SIFT features tolerate the residual elastic distortion that global
  minutiae matching cannot.

Measured results with press mode + SIGFM (threshold 8):

| comparison | SIGFM score |
|---|---|
| two presses of the same finger | **16-48** |
| mirrored print (impostor control) | 1 |

The patch ([`sigfm-x571gt.patch`](sigfm-x571gt.patch)) applied on top of the
`sigfm` branch adds:

- the `04f3:3104` id-table entry;
- a press-mode capture path for the `eFSA80SC` (single full-frame tone-mapped
  capture, no stitching, no rotation, since SIFT is rotation-invariant);
- `algorithm = FPI_DEVICE_ALGO_SIGFM` with a match threshold of 8, chosen
  from the measured genuine/impostor separation above;
- background self-healing: if the driver's calibration background was
  captured while a finger rested on the sensor, every later frame clamps to
  zero (`ip≈100`, `stddev≈0`) and the device is blind until restarted; the
  patch detects that signature and re-learns the background automatically;
- build fixes: OpenCV 5 support and optional `doctest` in the SIGFM meson
  files.

## Installing (Arch / Omarchy)

```bash
# 1. SPI buffer (mandatory, reboot or reload spidev afterwards)
sudo cp elan-spidev.conf /etc/modprobe.d/
sudo modprobe -r spidev && sudo modprobe spidev

# 2. Build and install the patched libfprint
cd pkg-sigfm
makepkg -f --nocheck --nodeps          # needs meson, ninja, glib2-devel, opencv
sudo pacman -U libfprint-1.94.100-2-x86_64.pkg.tar.zst
sudo systemctl restart fprintd

# 3. Enroll (see "How to press" below)
fprintd-enroll
fprintd-verify
```

On **Omarchy**, step 3 is nicer via the wizard, but its hardware detection is
USB-only and won't see an SPI sensor. Bypass the gate with the included fake
sysfs directory:

```bash
OMARCHY_USB_DEVICES_PATH=$PWD/fakeusb omarchy setup security fingerprint
```

On success it configures sudo, polkit, and the lock screen automatically.

### How to press

- **Press, don't swipe.** Flat fingertip pad on the sensor, hold ~1 second,
  lift fully, repeat. Enrollment takes 7 presses; shift the finger slightly
  between presses so more of the pad gets enrolled.
- Don't rest your finger on the sensor while fprintd is starting up. The
  driver self-heals from that now, but it costs a moment.

## Repo layout

```
README.md                  this document
elan-spidev.conf           the mandatory spidev buffer fix
sigfm-x571gt.patch         all driver changes, on goodix-fp-linux-dev/libfprint@sigfm
apply-sigfm-changes.py     re-applies the same changes to a fresh clone (patch alternative)
pkg-sigfm/                 Arch PKGBUILD + prebuilt package
diag-sigfm.sh              standalone enroll/verify test with debug logs (no fprintd needed)
fakeusb/                   fake sysfs dir to pass Omarchy's USB-only sensor detection
legacy/                    the earlier NBIS-era patch (working capture, failed matching).
                           Kept because its fixes (PID, 90° rotation, unsharp, drift clamp)
                           are what you'd upstream to mainline libfprint's swipe pipeline
```

## Caveats

- The package is versioned `1.94.100-2` (above Arch's `1.94.100-1`) so
  `pacman -Syu` won't replace it until the repo ships something newer.
  Then rebuild and reinstall, or pin with `IgnorePkg = libfprint`.
- `opencv` becomes a runtime dependency of libfprint (SIGFM uses SIFT).
- Security perspective: an 80x80 sensor sees ~4x4 mm of skin. This threshold
  was calibrated on one device to reject clear impostors, but a tiny sensor
  is inherently weaker than a full-size reader. Treat it as a convenience
  unlock, and keep a strong password.

## FAQ

### Why does the power-on prompt still want my password? Can't the fingerprint unlock the laptop from boot?

No, and it can't by design. The password you type when turning on the laptop
is not your login password, it is the **disk decryption key**. The whole disk
is LUKS-encrypted (the prompt says `omarchy_root`), and at that moment Linux
itself is still locked inside the encrypted disk. Step by step:

1. What runs at power-on is a tiny pre-boot environment (the initramfs)
   whose only job is to ask for the key and unlock the disk.
2. Everything fingerprint-related lives *inside* the encrypted disk:
   `fprintd`, this patched `libfprint` (and its OpenCV/SIGFM dependency),
   and your enrollment template. Chicken and egg: the fingerprint stack can
   only run once the disk is unlocked, and unlocking the disk needs the key
   first.
3. Even the sensor's drivers are not loaded at that stage: no touchpad HID,
   no `elanspi`, nothing that can talk to the reader yet.

So the finger covers everything *after* unlock: the lock screen, `sudo`, and
polkit. Type the disk password once at power-on; from login onward, the
fingerprint takes over.

Could this be made to work at boot someday? Other setups drive USB readers
from the initramfs before unlock, but this sensor would need the whole
libfprint + OpenCV + SIGFM stack and a calibration routine shipped inside
the initramfs, plus a copy of the fingerprint template stored in the
*unencrypted* boot partition, where anyone with the laptop could swap or
bypass it. That trades away most of what disk encryption buys you, and a
fingerprint is not a revocable key: you cannot change your finger the way
you change a leaked password. Keep a strong disk password, and treat the
fingerprint as the fast path for everything after boot.

## Credits

- [mincrmatt12/elan-spi-fingerprint](https://github.com/mincrmatt12/elan-spi-fingerprint):
  the original reverse engineering of ELAN SPI sensors and the mainline
  `elanspi` driver, plus the `bufsiz` discovery.
- [goodix-fp-linux-dev](https://github.com/goodix-fp-linux-dev): the SIGFM
  matcher and its libfprint integration.

## License

The libfprint patches are derivative of libfprint and are licensed
**LGPL-2.1-or-later** (see [`LICENSE`](LICENSE)). The standalone scripts in
this repo are MIT.
