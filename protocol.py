import struct

KNOWN_PARAMETERS = {
    (0x6c, 0x72, 3): "Tap (Hold)",

    (0x74, 0x1a, 3): "FX Knob (FX1)", 
    (0x74, 0x1c, 3): "FX Knob (FX2)", 
    (0x74, 0x1e, 3): "FX Knob (FX3)",

    (0x2a, 0x25, 0): "Drive",
    (0x2a, 0x24, 0): "Tone (part)",
    (0x74, 0x24, 3): "Volume",
    (0x74, 0x20, 3): "Reverb",

    (0x74, 0x48, 3): "FX1",
    (0x74, 0x47, 3): "FX2",
    (0x74, 0x46, 3): "FX3",
}

def decode_value(value):
    """ Turn the five byte value into a float. """
    flag = value[1]
    third = value[3]
    top = value[4]

    if (flag & 0x20):
        third |= 0x80
        
    # Create the four-byte sequence for struct.unpack
    float_bytes = b'\x00\x00' + bytes([third]) + bytes([top])
    return struct.unpack('<f', float_bytes)[0]

def classify(msg):
    if len(msg) >= 14:
        shape = (len(msg), msg[11], msg[13])
    else:
        shape = (len(msg), None, None)
    
    result = ("unknown", shape)

    if len(msg) == 45:
        if (msg[11] == 0x07):
            if (msg[13] == 0x04):
                param_id = (msg[22], msg[26], msg[27])
                value = decode_value(msg[35:40])
                result = ("param", param_id, value)
            elif (msg[13] == 0x03 and msg[26] == 0x7F):
                result = ("status",)       
    if 49 < len(msg) < 100:
        if msg[13] == 1:
            name = bytes(b for b in msg[49:-1] if 32 <= b < 127).decode()
            result = ("preset_info", name, msg[40]) 

    return result