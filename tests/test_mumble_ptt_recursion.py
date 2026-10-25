import unittest
from unittest.mock import Mock

from funkgateway.integrations.mumble_native import MumbleNativeClient


class MumblePTTRecursionTests(unittest.TestCase):

    def make_client(self, gateway_rx=False):
        client = MumbleNativeClient.__new__(MumbleNativeClient)
        client._pc_ptt_active = False
        client._gateway_rx_active = gateway_rx
        client._own_tx_active = gateway_rx
        client._pc_ptt_enabled = True
        client._connected = True
        client._capture_thread = None
        client._start_capture = Mock()
        return client

    def test_repeated_ptt_off_does_not_emit(self):
        client = self.make_client()
        emit = Mock()
        client._emit_participants = emit

        client.set_pc_ptt(False)
        client.set_pc_ptt(False)

        self.assertFalse(client._pc_ptt_active)
        emit.assert_not_called()

    def test_mute_callback_does_not_recurse(self):
        client = self.make_client()
        calls = []

        def emit():
            calls.append(True)
            if len(calls) > 5:
                raise RuntimeError("PTT-Endlosrekursion")
            client.set_pc_ptt(False)

        client._emit_participants = emit
        client.set_pc_ptt(True)

        self.assertFalse(client._pc_ptt_active)
        self.assertFalse(client._own_tx_active)
        self.assertEqual(len(calls), 2)

        client.set_pc_ptt(False)
        self.assertEqual(len(calls), 2)

    def test_gateway_rx_survives_mute(self):
        client = self.make_client(gateway_rx=True)
        calls = []

        def emit():
            calls.append(True)
            if len(calls) > 5:
                raise RuntimeError("PTT-Endlosrekursion")
            client.set_pc_ptt(False)

        client._emit_participants = emit
        client.set_pc_ptt(True)

        self.assertFalse(client._pc_ptt_active)
        self.assertTrue(client._gateway_rx_active)
        self.assertTrue(client._own_tx_active)
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
