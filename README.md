# Headphone Cue for MallMuzik

An NVDA add-on that makes NVDA speak through channels 3 and 4 (the headphone cue) of a DJ controller, so the DJ hears the screen reader in the headphones and the audience never hears it on the speakers.

Made for blind DJs who use MallMuzik together with VirtualDJ. It works with any DJ controller that has its own sound card with 4 output channels (master on 1 and 2, headphones on 3 and 4), for example the Numark Mixtrack Pro and the Pioneer DDJ-FLX4.

## Download

[MallMuzik-Headphone-Cue-0.2.4.nvda-addon](releases/MallMuzik-Headphone-Cue-0.2.4.nvda-addon)

## How to use

1. Install the add-on and restart NVDA.
2. Open NVDA Settings, category **Headphone Cue**.
3. Check "Speak only in the controller headphones (channels 3 and 4)" and choose your controller.

If the controller is disconnected, NVDA goes back to your usual sound card.

In VirtualDJ (or any other DJ software), choose the WASAPI or Windows audio driver for the controller. The ASIO driver takes the sound card only for the DJ software, and then the NVDA voice falls back to the speakers.

## Languages

English, Brazilian Portuguese and Spanish.

## Author

DJ Anderson Farias (CAF Eventos) <djandersonfarias@gmail.com>

## License

GNU General Public License, version 2 (see COPYING.txt).
