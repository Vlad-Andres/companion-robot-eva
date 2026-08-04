import struct
from array import array


def apply_wav_volume(wav_bytes: bytes, volume_percent: int) -> bytes:
    if not wav_bytes:
        return wav_bytes

    try:
        vol = int(volume_percent)
    except Exception:
        return wav_bytes

    vol = max(0, min(100, vol))
    if vol == 100:
        return wav_bytes

    if len(wav_bytes) < 12 or wav_bytes[0:4] != b"RIFF" or wav_bytes[8:12] != b"WAVE":
        return wav_bytes

    fmt: tuple[int, int, int] | None = None
    data_offset: int | None = None
    data_size: int | None = None

    i = 12
    n = len(wav_bytes)
    while i + 8 <= n:
        chunk_id = wav_bytes[i : i + 4]
        chunk_size = int.from_bytes(wav_bytes[i + 4 : i + 8], "little", signed=False)
        chunk_data_start = i + 8
        chunk_data_end = min(n, chunk_data_start + chunk_size)

        if chunk_id == b"fmt " and (chunk_data_end - chunk_data_start) >= 16:
            audio_format, channels, _rate, _byte_rate, _block_align, bits = struct.unpack_from(
                "<HHIIHH", wav_bytes, chunk_data_start
            )
            fmt = (int(audio_format), int(bits), int(channels))
        elif chunk_id == b"data":
            data_offset = chunk_data_start
            data_size = chunk_data_end - chunk_data_start

        step = 8 + chunk_size
        if step % 2 == 1:
            step += 1
        i += step

        if fmt is not None and data_offset is not None:
            break

    if fmt is None or data_offset is None or data_size is None:
        return wav_bytes

    audio_format, bits_per_sample, _channels = fmt
    if audio_format != 1 or bits_per_sample != 16:
        return wav_bytes

    factor = float(vol) / 100.0
    end = data_offset + data_size
    end = end - ((end - data_offset) % 2)
    if end <= data_offset:
        return wav_bytes

    buf = bytearray(wav_bytes)
    pcm = bytes(buf[data_offset:end])

    samples = array("h")
    samples.frombytes(pcm)

    for idx, s in enumerate(samples):
        v = int(float(s) * factor)
        if v > 32767:
            v = 32767
        elif v < -32768:
            v = -32768
        samples[idx] = v

    buf[data_offset:end] = samples.tobytes()
    return bytes(buf)
