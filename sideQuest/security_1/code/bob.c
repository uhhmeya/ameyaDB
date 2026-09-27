#include "LOL.h"

#define PREAMBLE 0xAA

static uint8_t receive(void *line[LINES]) {
    for (;;) {
        for (int b = 0; b < 8; b++) flush(line[1 + b]);
        if (sense(line[REQ])) break;
    }
    int vote[8] = {0};
    for (int k = 0; k < VOTES; k++) {
        for (int b = 0; b < 8; b++) flush(line[1 + b]);
        for (volatile int d = 0; d < 300; d++);
        for (int b = 0; b < 8; b++)
            if (reload(line[1 + b]) < THRESHOLD) vote[b]++;
    }
    uint8_t byte = 0;
    for (int b = 0; b < 8; b++)
        if (vote[b] * 2 > VOTES) byte |= (1 << b);
    int lo = 0;
    while (lo < DEB) {
        for (int r = 0; r < REPS; r++) maccess(line[ACK]);
        lo = sense(line[REQ]) ? 0 : lo + 1;
    }
    return byte;
}

int main(void) {
    void *line[LINES];
    map_lines(line);

    printf("Please press enter.\n");
    getchar();
    printf("Receiver now listening.\n");

    while (receive(line) != PREAMBLE);
    for (;;) {
        uint8_t c = receive(line);
        putchar(c);
        fflush(stdout);
        if (c == '\n') break;
    }
    return 0;
}