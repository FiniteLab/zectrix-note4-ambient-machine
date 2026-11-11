/* SPDX-License-Identifier: MPL-2.0 */
#include <errno.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "amb.h"

void en_midi_out(uint32_t st, uint32_t d1, uint32_t d2)
{
    (void)st;
    (void)d1;
    (void)d2;
}

static void put16(FILE *file, uint16_t value)
{
    uint8_t bytes[2] = {value & 255, value >> 8};
    fwrite(bytes, 1, 2, file);
}

static void put32(FILE *file, uint32_t value)
{
    uint8_t bytes[4] = {value & 255, (value >> 8) & 255, (value >> 16) & 255, value >> 24};
    fwrite(bytes, 1, 4, file);
}

static int wav_header(FILE *file, uint32_t frames)
{
    uint32_t bytes = frames * 4;
    if (fseek(file, 0, SEEK_SET) != 0)
        return -1;
    fwrite("RIFF", 1, 4, file);
    put32(file, 36 + bytes);
    fwrite("WAVEfmt ", 1, 8, file);
    put32(file, 16);
    put16(file, 1);
    put16(file, 2);
    put32(file, 44100);
    put32(file, 44100 * 4);
    put16(file, 4);
    put16(file, 16);
    fwrite("data", 1, 4, file);
    put32(file, bytes);
    return ferror(file) ? -1 : 0;
}

static long number(const char *text, long lo, long hi, const char *label)
{
    char *end;
    long value;
    errno = 0;
    value = strtol(text, &end, 10);
    if (errno || *end || value < lo || value > hi) {
        fprintf(stderr, "%s 应在 %ld～%ld 之间\n", label, lo, hi);
        exit(2);
    }
    return value;
}

int main(int argc, char **argv)
{
    int16_t parameters[P_NPARAMS];
    uint16_t pool;
    int32_t buffer[512];
    uint32_t seed = 42;
    uint32_t seconds = 60;
    uint32_t frame = 0;
    uint32_t total;
    FILE *file;
    float peak = 0.0f;
    double square_sum = 0.0;
    uint32_t clipped = 0;
    int32_t held[2] = {0, 0};
    uint32_t stuck = 0;
    int broken = 0;
    int piece = -1;
    int index;
    int override_ids[P_NPARAMS];
    int override_values[P_NPARAMS];
    int override_count = 0;
    int argument = 4;

    if (argc == 1) {
        for (index = 0; index < EN_NPIECES; index++)
            printf("%d: %s\n", index, en_piece_name(index));
        printf("用法：amb-render <预设编号> <秒数> <输出.wav> [随机种子]\n");
        return 0;
    }
    if (argc == 3 && !strcmp(argv[1], "--defaults")) {
        piece = (int)number(argv[2], 0, EN_NPIECES - 1, "预设编号");
        en_piece(piece, parameters, &pool);
        for (index = 0; index < P_NPARAMS; index++)
            printf("%d %d\n", index, parameters[index]);
        return 0;
    }
    if (argc < 4) {
        fprintf(stderr, "用法：amb-render <预设编号> <秒数> <输出.wav> [随机种子] [--set 编号=值 ...]\n");
        return 2;
    }
    piece = (int)number(argv[1], 0, EN_NPIECES - 1, "预设编号");
    seconds = (uint32_t)number(argv[2], 1, 600, "秒数");
    if (argument < argc && strcmp(argv[argument], "--set")) {
        seed = (uint32_t)number(argv[argument], 0, 0x7fffffff, "随机种子");
        argument++;
    }
    while (argument < argc) {
        const char *assignment;
        const char *equals;
        char name[32], value[32];
        size_t name_length, value_length;
        if (argument + 1 >= argc || strcmp(argv[argument], "--set")) {
            fprintf(stderr, "--set 需要 <参数编号=参数值>\n");
            return 2;
        }
        assignment = argv[argument + 1];
        equals = strchr(assignment, '=');
        name_length = equals ? (size_t)(equals - assignment) : 0;
        value_length = equals ? strlen(equals + 1) : 0;
        if (!name_length || name_length >= sizeof name || !value_length || value_length >= sizeof value) {
            fprintf(stderr, "参数格式应为 <编号=值>\n");
            return 2;
        }
        memcpy(name, assignment, name_length);
        name[name_length] = 0;
        memcpy(value, equals + 1, value_length + 1);
        if (override_count >= P_NPARAMS) {
            fprintf(stderr, "参数覆盖过多\n");
            return 2;
        }
        override_ids[override_count] = (int)number(name, 0, P_NPARAMS - 1, "参数编号");
        override_values[override_count] = (int)number(value, -1000, 1000, "参数值");
        override_count++;
        argument += 2;
    }
    file = fopen(argv[3], "wb");
    if (!file) {
        perror("无法创建 WAV");
        return 1;
    }
    {
        static const uint8_t empty[44] = {0};
        fwrite(empty, 1, sizeof empty, file);
    }
    en_piece(piece, parameters, &pool);
    en_init();
    for (index = 0; index < P_NPARAMS; index++)
        en_set(index, parameters[index]);
    en_pool(pool);
    for (index = 0; index < override_count; index++)
        en_set(override_ids[index], override_values[index]);
    en_seed(seed);
    en_play(1);
    total = seconds * 44100u;
    while (frame < total) {
        uint32_t count = total - frame > 256 ? 256 : total - frame;
        uint32_t i;
        uint8_t bytes[1024];
        en_render(buffer, count, 2048);
        /* A NaN inside the engine saturates the output stage: the level stops moving while staying nonzero. */
        for (i = 0; i < count; i++) {
            int32_t left = buffer[i * 2], right = buffer[i * 2 + 1];
            if ((left || right) && left == held[0] && right == held[1]) {
                if (++stuck >= 44100)
                    broken = 1;
            } else {
                stuck = 0;
            }
            held[0] = left;
            held[1] = right;
        }
        for (i = 0; i < count * 2; i++) {
            float value = (float)buffer[i] / 8388608.0f;
            uint32_t remaining = total - frame - i / 2;
            int sample;
            if (remaining < 88200)
                value *= (float)remaining / 88200.0f;
            if (fabsf(value) > peak)
                peak = fabsf(value);
            if (value < -1.0f || value > 1.0f)
                clipped++;
            square_sum += (double)value * value;
            sample = (int)(value * 32767.0f);
            if (sample > 32767)
                sample = 32767;
            if (sample < -32768)
                sample = -32768;
            bytes[i * 2] = (uint8_t)(sample & 255);
            bytes[i * 2 + 1] = (uint8_t)((uint16_t)sample >> 8);
        }
        fwrite(bytes, 2, count * 2, file);
        frame += count;
    }
    if (wav_header(file, total) != 0 || fclose(file) != 0) {
        fprintf(stderr, "WAV 写入失败\n");
        return 1;
    }
    if (broken) {
        remove(argv[3]);
        fprintf(stderr, "渲染输出异常：恒定非零电平持续超过 1 秒，已丢弃 WAV\n");
        return 1;
    }
    printf("预设: %s；时长: %u 秒；峰值: %.3f；RMS: %.4f；越界样本: %u\n",
           en_piece_name(piece), seconds, (double)peak,
           sqrt(square_sum / ((double)total * 2.0)), clipped);
    printf("WAV: %s\n", argv[3]);
    return 0;
}
