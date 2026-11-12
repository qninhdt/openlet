import grpc


def channel(address, *, tls=False, max_bytes):
    options = [
        ("grpc.max_receive_message_length", max_bytes),
        ("grpc.max_send_message_length", max_bytes),
    ]
    if tls:
        return grpc.aio.secure_channel(address, grpc.ssl_channel_credentials(), options)
    return grpc.aio.insecure_channel(address, options)
