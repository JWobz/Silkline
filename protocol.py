import struct

KNOWN_PARAMETERS = {
    #0x02: "Tap",

    0x25: "Drive",
    0x24: "Volume",

    0x48: "FX1",
    0x47: "FX2",
    0x46: "FX3",

    0x1C: "FX"
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

    if (len(msg) == 45 and msg[11] == 0x07):
        if (msg[13] == 0x04):
            param_id = msg[26]
            value = decode_value(msg[35:40])
            result = ("param", param_id, value)
        elif (msg[13] == 0x03 and msg[26] == 0x7F):
            result = ("status",)  

    return result