# Vendored front-end libraries

Served from this folder because the dashboard's Content-Security-Policy only allows scripts, styles and fonts from its own origin.
Nothing here is loaded from a CDN at run time. To update, download the same file from jsDelivr at the new version and replace it.

| Library | Version | License |
|---|---|---|
| Lenis (smooth scroll) | 1.3.27 | MIT |
| GSAP + ScrollTrigger | 3.15.1 | GreenSock Standard License (free to use; see https://gsap.com/standard-license). Not MIT. |
| three.js (Vanta's engine) | r134 (0.134.0) | MIT. Pinned to r134 because Vanta 0.5.x expects the global build. |
| Vanta (NET background) | 0.5.24 | MIT |
| Motion | 14.14.0 | MIT |
| AOS | 2.3.4 | MIT |
| Fira Sans, Fira Code (via Fontsource) | 5.x | SIL Open Font License 1.1 |

React Bits (DavidHDev/react-bits) is a React component collection and this front end has no React, so none of its code is vendored.
The count-up, spotlight-card and shiny-text effects are small vanilla re-implementations of those ideas.

| File | Bytes | SHA-256 (prefix) |
|---|---|---|
| `LICENSE-aos.txt` | 1083 | `4d1f9c2c1c7597f1…` |
| `LICENSE-fira-sans.txt` | 4314 | `18aabf190848725e…` |
| `LICENSE-lenis.txt` | 1088 | `7d1896b31f2eed9f…` |
| `LICENSE-motion.txt` | 1100 | `1bf0dc3f7727723e…` |
| `LICENSE-three.txt` | 1081 | `7dddf7c5b8fd10ee…` |
| `LICENSE-vanta.txt` | 1055 | `abcd0d2be97f3ab1…` |
| `ScrollTrigger.min.js` | 44683 | `b5bb360661f478f0…` |
| `aos.css` | 26053 | `1aa8845fd06e475a…` |
| `aos.js` | 14690 | `a5005b2e414770fd…` |
| `fonts/fira-code-400.woff2` | 23312 | `6dc9da171ccea71d…` |
| `fonts/fira-code-500.woff2` | 23316 | `9e4da5ad2c147be0…` |
| `fonts/fira-code-600.woff2` | 23316 | `53bd904d81c086b1…` |
| `fonts/fira-sans-400.woff2` | 23872 | `3e38d8c01fe97529…` |
| `fonts/fira-sans-500.woff2` | 24056 | `88d3e420adee3fa9…` |
| `fonts/fira-sans-600.woff2` | 24844 | `55e09735e30d8492…` |
| `fonts/fira-sans-700.woff2` | 25012 | `c753d7153cac2cfe…` |
| `gsap.min.js` | 73357 | `3d1bea374ab1b703…` |
| `lenis.min.js` | 18815 | `80f53e77f1c13e37…` |
| `motion.js` | 191561 | `521cfef8910fdd99…` |
| `three.min.js` | 615601 | `74782bdbcf6518f7…` |
| `vanta.net.min.js` | 13225 | `76fe5829c73c27aa…` |
