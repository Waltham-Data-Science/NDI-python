# Bundled assets

## `ndi_cloud_logo.png`

The NDI Cloud wordmark, copied byte-for-byte from NDI-matlab at
`src/ndi/+ndi/+cloud/+ui/resources/images/ndi_logo.png` (1682x306,
md5 3e8439f1b1b8686b38ad71f314fff157), which is the same file that repo
serves to its own cloud dialogs and to the metadata app.

Copied rather than referenced because the viewer runs from a Python
install that need not have NDI-matlab on disk at all -- a downloaded
dataset opened by someone who has never run MATLAB is the normal case.

It is a WORDMARK IN DARK NAVY on transparency, so it is drawn on a white
card: napari's docks follow the viewer's theme, and navy on the dark one
is invisible. The card is how the brand is used elsewhere anyway.
