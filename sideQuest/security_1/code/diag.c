#define _GNU_SOURCE
#include "LOL.h"
#include <sched.h>
#include <signal.h>
#include <sys/wait.h>

static void pin(int cpu) {
    cpu_set_t set; CPU_ZERO(&set); CPU_SET(cpu, &set);
    sched_setaffinity(0, sizeof(set), &set);
}

int main(void) {
    void *line[LINES];
    map_lines(line);
    uint8_t target = 0xAA;

    pid_t pid = fork();
    if (pid == 0) {
        pin(4);
        for (;;) {
            for (int b = 0; b < 8; b++)
                if (target & (1 << b)) maccess(line[1 + b]);
            maccess(line[REQ]);
        }
        _exit(0);
    }
    pin(2);

    int N = 20000, reqhot = 0;
    unsigned long reqmin = ~0UL, reqsum = 0;
    long hist[256] = {0};
    for (int i = 0; i < N; i++) {
        for (int b = 0; b < 8; b++) flush(line[1 + b]);
        flush(line[REQ]);
        for (volatile int d = 0; d < 500; d++);
        unsigned long rl = reload(line[REQ]);
        if (rl < reqmin) reqmin = rl;
        reqsum += rl;
        if (rl < THRESHOLD) {
            reqhot++;
            uint8_t byte = 0;
            for (int b = 0; b < 8; b++)
                if (reload(line[1 + b]) < THRESHOLD) byte |= (1 << b);
            hist[byte]++;
        }
    }
    kill(pid, SIGKILL); wait(NULL);

    printf("REQ hot on %d of %d polls   (min latency %lu, avg %lu)\n",
           reqhot, N, reqmin, reqsum / N);
    printf("target byte = 0x%02X\n", target);
    printf("decoded bytes seen while REQ hot:\n");
    for (int v = 0; v < 256; v++)
        if (hist[v]) printf("   0x%02X : %ld\n", v, hist[v]);
    return 0;
}