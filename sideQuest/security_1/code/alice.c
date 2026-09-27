#include "LOL.h"

#define PREAMBLE 0xAA

static void send(void *line[LINES], uint8_t byte) {
    for (;;) {
        for (int r = 0; r < REPS; r++) {
            for (int b = 0; b < 8; b++)
                if (byte & (1 << b)) maccess(line[1 + b]);
            maccess(line[REQ]);
        }
        if (sense(line[ACK])) break;
    }
    int lo = 0;
    while (lo < DEB)
        lo = sense(line[ACK]) ? 0 : lo + 1;
}

int main(void) {
    void *line[LINES];
    map_lines(line);

    char msg[256];
    printf("Please type a message.\n");
    if (!fgets(msg, sizeof(msg), stdin)) return 0;

    send(line, PREAMBLE);
    for (int c = 0; msg[c] != '\0'; c++)
        send(line, (uint8_t)msg[c]);
    return 0;
}