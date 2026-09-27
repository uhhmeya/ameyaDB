#define _GNU_SOURCE
#include "LOL.h"
#include <sched.h>
#include <sys/wait.h>

#define PREAMBLE 0xAA

static void pin(int cpu) {
    cpu_set_t set; CPU_ZERO(&set); CPU_SET(cpu, &set);
    sched_setaffinity(0, sizeof(set), &set);
}

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

    const char *msg = "Hello, World!\n";

    pid_t pid = fork();
    if (pid == 0) {
        pin(4);
        send(line, PREAMBLE);
        for (int i = 0; msg[i]; i++) send(line, (uint8_t)msg[i]);
        _exit(0);
    }

    pin(2);
    printf("self-test receiving: ");
    fflush(stdout);
    while (receive(line) != PREAMBLE);
    for (;;) {
        uint8_t c = receive(line);
        putchar(c);
        fflush(stdout);
        if (c == '\n') break;
    }
    wait(NULL);
    return 0;
}