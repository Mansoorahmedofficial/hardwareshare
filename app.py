import streamlit as st

from relay import InputController, InputReceiver, local_ip, new_pairing_code

st.set_page_config(page_title="Hardshare", page_icon="H", layout="centered")

if "pairing_code" not in st.session_state:
    st.session_state.pairing_code = new_pairing_code()
if "receiver" not in st.session_state:
    st.session_state.receiver = None
if "controller" not in st.session_state:
    st.session_state.controller = None

st.title("Hardshare")
st.caption("Use one keyboard and mouse across two computers on your local Wi-Fi.")
st.warning(
    "Only pair devices on a Wi-Fi network you trust. While sharing, input is redirected "
    "to the other computer. Press Ctrl+Alt+Esc on the controlling computer to stop."
)

receive_tab, control_tab = st.tabs(
    ("Receive control", "Control another computer"))

with receive_tab:
    st.subheader("This computer receives input")
    st.write(
        "Start the receiver, then enter this address and pairing code on the other computer.")
    st.text_input("This computer's Wi-Fi address",
                  value=local_ip(), disabled=True)
    st.code(st.session_state.pairing_code, language=None)

    receiver = st.session_state.receiver
    if receiver is None or receiver.status in ("Stopped",) or receiver.status.startswith("Error:"):
        if st.button("Start receiving", type="primary", key="start_receiver"):
            receiver = InputReceiver(st.session_state.pairing_code)
            st.session_state.receiver = receiver
            receiver.start()
    else:
        if st.button("Stop receiving", key="stop_receiver"):
            receiver.stop()
            st.session_state.receiver = None

    @st.fragment(run_every=1)
    def receiver_status() -> None:
        current = st.session_state.receiver
        if current is not None:
            state = current.status
            if state.startswith("Error:"):
                st.error(state)
            elif state == "Connected":
                st.success(
                    "Connected. This computer is receiving keyboard and mouse input.")
            else:
                st.info(state)

    receiver_status()

with control_tab:
    st.subheader("This computer controls another")
    st.write("Enter the receiver's Wi-Fi address and the code shown on that computer.")
    with st.form("connect_form"):
        address = st.text_input("Receiver Wi-Fi address",
                                placeholder="192.168.1.25")
        code = st.text_input("Pairing code", max_chars=8).strip().upper()
        start_sharing = st.form_submit_button(
            "Connect and start sharing", type="primary")

    if start_sharing:
        if not address or len(code) != 8:
            st.error(
                "Enter the receiver's address and its 8-character pairing code.")
        else:
            try:
                controller = InputController()
                controller.connect(address, code)
                st.session_state.controller = controller
                st.rerun()
            except Exception as error:
                st.error(f"Could not start sharing: {error}")

    @st.fragment(run_every=1)
    def controller_status() -> None:
        current = st.session_state.controller
        if current is None:
            return
        if current.status == "Stopped":
            st.info("Sharing stopped. Reload this page to connect again.")
        else:
            st.success(current.status)
            st.caption("Stop sharing with Ctrl+Alt+Esc on this computer.")

    controller_status()

st.divider()
st.caption(
    "Sharing is a manual toggle. Automatic screen-edge switching is not included yet.")
