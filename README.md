# Hardshare

Share one computer's keyboard and mouse with another computer on the same trusted Wi-Fi network.
Both computers run this app. One computer receives input; the other connects using the receiver's
LAN address and an 8-character pairing code.

## Run

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
streamlit run app.py --server.address 0.0.0.0
```

Install and run the app locally on both computers. Open `http://localhost:8501` on each one; do not
use one computer's Streamlit page from the other, because input capture runs on the machine hosting
that Streamlit process. On the receiving computer, choose **Receive control**
and start the receiver. On the controlling computer, choose **Control another computer**, enter the
receiver's Wi-Fi address and displayed code, then start sharing. Allow TCP port `8765` through the
receiver's firewall if prompted. Streamlit's port `8501` is only needed to open the app remotely;
it is not required when each computer opens its own local page.

Press `Ctrl+Alt+Esc` on the controlling computer to stop immediately. The receiver also releases any
keys or mouse buttons that were held when a connection ends.

## Platform notes

`pynput` needs a graphical desktop session on both computers. On Linux, use an X11 session; Wayland
may prevent global input capture or suppression. Input suppression support varies by platform, so
test on both computers before relying on it. macOS may ask for Accessibility permission. This app
does not implement automatic screen-edge switching or clipboard sharing.

Pair only on a trusted private network. The pairing code authorizes the connection but traffic is not
encrypted, so do not expose port `8765` to the internet or an untrusted network.

## Tests

```bash
python -m unittest discover -s tests
```