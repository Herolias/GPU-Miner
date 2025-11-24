CUDA_SOURCE = r"""
#include <cuda_runtime.h>
// FORCE RECOMPILE 11
#include <stdint.h>

typedef unsigned char uint8_t;
typedef unsigned long long uint64_t;
typedef unsigned int uint32_t;
typedef int int32_t;

#define BLAKE2B_BLOCKBYTES 128
#define BLAKE2B_OUTBYTES 64
#define INSTR_SIZE 20
#define NB_REGS 32
#define REGS_BITS 5
#define REGS_INDEX_MASK 31
#define REGISTER_SIZE 8
#define ROM_ACCESS_SIZE 64
#define MIX_STREAM_BYTES (NB_REGS * REGISTER_SIZE * 32)

// --- BLAKE2B ---

__device__ const uint64_t blake2b_IV[8] = {
    0x6a09e667f3bcc908ULL, 0xbb67ae8584caa73bULL,
    0x3c6ef372fe94f82bULL, 0xa54ff53a5f1d36f1ULL,
    0x510e527fade682d1ULL, 0x9b05688c2b3e6c1fULL,
    0x1f83d9abfb41bd6bULL, 0x5be0cd19137e2179ULL
};

__device__ const uint8_t blake2b_sigma[12][16] = {
    {  0,  1,  2,  3,  4,  5,  6,  7,  8,  9, 10, 11, 12, 13, 14, 15 },
    { 14, 10,  4,  8,  9, 15, 13,  6,  1, 12,  0,  2, 11,  7,  5,  3 },
    { 11,  8, 12,  0,  5,  2, 15, 13, 10, 14,  3,  6,  7,  1,  9,  4 },
    {  7,  9,  3,  1, 13, 12, 11, 14,  2,  6,  5, 10,  4,  0, 15,  8 },
    {  9,  0,  5,  7,  2,  4, 10, 15, 14,  1, 11, 12,  6,  8,  3, 13 },
    {  2, 12,  6, 10,  0, 11,  8,  3,  4, 13,  7,  5, 15, 14,  1,  9 },
    { 12,  5,  1, 15, 14, 13,  4, 10,  0,  7,  6,  3,  9,  2,  8, 11 },
    { 13, 11,  7, 14, 12,  1,  3,  9,  5,  0, 15,  4,  8,  6,  2, 10 },
    {  6, 15, 14,  9, 11,  3,  0,  8, 12,  2, 13,  7,  1,  4, 10,  5 },
    { 10,  2,  8,  4,  7,  6,  1,  5, 15, 11,  9, 14,  3, 12, 13,  0 },
    {  0,  1,  2,  3,  4,  5,  6,  7,  8,  9, 10, 11, 12, 13, 14, 15 },
    { 14, 10,  4,  8,  9, 15, 13,  6,  1, 12,  0,  2, 11,  7,  5,  3 }
};

__device__ __forceinline__ uint64_t rotr64(const uint64_t w, const unsigned c) {
    return (w >> c) | (w << (64 - c));
}

struct Blake2bCtx {
    uint64_t h[8];
    uint64_t t[2];
    uint64_t f[2];
    uint8_t buf[BLAKE2B_BLOCKBYTES];
    size_t buflen;
};

__device__ void blake2b_compress(uint64_t h[8], const uint8_t block[BLAKE2B_BLOCKBYTES], uint64_t t[2], uint64_t f[2]) {
    uint64_t m[16];
    uint64_t v[16];
    int i;

    #pragma unroll
    for(i = 0; i < 16; ++i) {
        m[i] = ((uint64_t)block[i * 8]) |
               ((uint64_t)block[i * 8 + 1] << 8) |
               ((uint64_t)block[i * 8 + 2] << 16) |
               ((uint64_t)block[i * 8 + 3] << 24) |
               ((uint64_t)block[i * 8 + 4] << 32) |
               ((uint64_t)block[i * 8 + 5] << 40) |
               ((uint64_t)block[i * 8 + 6] << 48) |
               ((uint64_t)block[i * 8 + 7] << 56);
    }

    #pragma unroll
    for(i = 0; i < 8; ++i) v[i] = h[i];
    v[8] = blake2b_IV[0];
    v[9] = blake2b_IV[1];
    v[10] = blake2b_IV[2];
    v[11] = blake2b_IV[3];
    v[12] = blake2b_IV[4] ^ t[0];
    v[13] = blake2b_IV[5] ^ t[1];
    v[14] = blake2b_IV[6] ^ f[0];
    v[15] = blake2b_IV[7] ^ f[1];

    #pragma unroll
    for(i = 0; i < 12; ++i) {
        #define G(r,i,a,b,c,d) \
            do { \
                a = a + b + m[blake2b_sigma[r][2*i]]; \
                d = rotr64(d ^ a, 32); \
                c = c + d; \
                b = rotr64(b ^ c, 24); \
                a = a + b + m[blake2b_sigma[r][2*i+1]]; \
                d = rotr64(d ^ a, 16); \
                c = c + d; \
                b = rotr64(b ^ c, 63); \
            } while(0)
        G(i,0,v[ 0],v[ 4],v[ 8],v[12]);
        G(i,1,v[ 1],v[ 5],v[ 9],v[13]);
        G(i,2,v[ 2],v[ 6],v[10],v[14]);
        G(i,3,v[ 3],v[ 7],v[11],v[15]);
        G(i,4,v[ 0],v[ 5],v[10],v[15]);
        G(i,5,v[ 1],v[ 6],v[11],v[12]);
        G(i,6,v[ 2],v[ 7],v[ 8],v[13]);
        G(i,7,v[ 3],v[ 4],v[ 9],v[14]);
        #undef G
    }
    #pragma unroll
    for(i = 0; i < 8; ++i) h[i] ^= v[i] ^ v[i + 8];
}

__device__ void blake2b_init(Blake2bCtx* ctx, uint8_t outlen) {
    for(int i=0; i<8; i++) ctx->h[i] = blake2b_IV[i];
    ctx->h[0] ^= 0x01010000 | (uint32_t)outlen; 
    ctx->t[0] = 0; ctx->t[1] = 0;
    ctx->f[0] = 0; ctx->f[1] = 0;
    ctx->buflen = 0;
}

__device__ void blake2b_update(Blake2bCtx* ctx, const void* in, size_t inlen) {
    const uint8_t* pin = (const uint8_t*)in;
    while(inlen > 0) {
        size_t left = ctx->buflen;
        size_t fill = BLAKE2B_BLOCKBYTES - left;
        if(inlen > fill) {
            for(size_t i=0; i<fill; i++) ctx->buf[left+i] = pin[i];
            ctx->buflen += fill;
            ctx->t[0] += BLAKE2B_BLOCKBYTES;
            if(ctx->t[0] < BLAKE2B_BLOCKBYTES) ctx->t[1]++; 
            blake2b_compress(ctx->h, ctx->buf, ctx->t, ctx->f);
            ctx->buflen = 0;
            pin += fill;
            inlen -= fill;
        } else {
            for(size_t i=0; i<inlen; i++) ctx->buf[left+i] = pin[i];
            ctx->buflen += inlen;
            pin += inlen;
            inlen = 0;
        }
    }
}

__device__ void blake2b_final(Blake2bCtx* ctx, void* out) {
    ctx->t[0] += ctx->buflen;
    if(ctx->t[0] < ctx->buflen) ctx->t[1]++;
    ctx->f[0] = 0xFFFFFFFFFFFFFFFFULL;
    for(size_t i=ctx->buflen; i<BLAKE2B_BLOCKBYTES; i++) ctx->buf[i] = 0;
    blake2b_compress(ctx->h, ctx->buf, ctx->t, ctx->f);
    uint8_t* pout = (uint8_t*)out;
    for(int i=0; i<8; i++) {
        uint64_t val = ctx->h[i];
        pout[i*8+0] = val; pout[i*8+1] = val>>8; pout[i*8+2] = val>>16; pout[i*8+3] = val>>24;
        pout[i*8+4] = val>>32; pout[i*8+5] = val>>40; pout[i*8+6] = val>>48; pout[i*8+7] = val>>56;
    }
}

// --- STREAMING BLAKE2B ---

struct Blake2bStream {
    uint8_t prev[64];
    uint32_t produced;
    uint32_t buffer_pos; 
    uint32_t buffer_limit;
    uint32_t total_len;
};

__device__ void blake2b_stream_init(Blake2bStream* s, uint32_t outlen, const uint8_t* seed) {
    s->total_len = outlen;
    s->produced = 0;
    s->buffer_pos = 0;

    if (outlen <= 64) {
        Blake2bCtx ctx;
        blake2b_init(&ctx, (uint8_t)outlen);
        blake2b_update(&ctx, &outlen, 4);
        blake2b_update(&ctx, seed, 64);
        blake2b_final(&ctx, s->prev);
        s->buffer_limit = outlen;
    } else {
        Blake2bCtx ctx;
        blake2b_init(&ctx, 64);
        blake2b_update(&ctx, &outlen, 4);
        blake2b_update(&ctx, seed, 64);
        blake2b_final(&ctx, s->prev);
        s->buffer_limit = 32;
    }
}

__device__ uint8_t blake2b_stream_next(Blake2bStream* s) {
    if (s->produced >= s->total_len) return 0;

    if (s->buffer_pos >= s->buffer_limit) {
        // Refill buffer
        uint32_t remaining = s->total_len - s->produced;
        
        if (remaining > 64) {
            // Continue loop: Hash(prev) -> prev, take 32 bytes
            Blake2bCtx iter;
            blake2b_init(&iter, 64);
            blake2b_update(&iter, s->prev, 64);
            blake2b_final(&iter, s->prev);
            s->buffer_limit = 32;
        } else {
            // Final block: Hash(remaining, prev) -> prev, take remaining bytes
            Blake2bCtx final_ctx;
            blake2b_init(&final_ctx, (uint8_t)remaining);
            blake2b_update(&final_ctx, s->prev, 64);
            blake2b_final(&final_ctx, s->prev);
            s->buffer_limit = remaining;
        }
        s->buffer_pos = 0;
    }

    uint8_t val = s->prev[s->buffer_pos];
    s->buffer_pos++;
    s->produced++;
    return val;
}

__device__ void blake2b_stream_fill(Blake2bStream* s, uint8_t* dest, uint32_t count) {
    for(uint32_t i=0; i<count; i++) {
        dest[i] = blake2b_stream_next(s);
    }
}

// --- HELPERS ---

__device__ uint64_t isqrt(uint64_t n) {
    if (n < 2) return n;
    uint64_t x = n;
    uint64_t y = (x + 1) >> 1;
    while (y < x) {
        x = y;
        y = (x + n / x) >> 1;
    }
    return x;
}

__device__ __forceinline__ uint64_t bit_rev(uint64_t n) {
    return __brevll(n);
}

__device__ __forceinline__ uint64_t load_le_u64(const uint8_t* src) {
    uint64_t v = 0;
    for(int i=0; i<8; i++) {
        v |= ((uint64_t)src[i]) << (i*8);
    }
    return v;
}

__device__ __forceinline__ uint32_t load_be_u32(const uint8_t* src) {
    return ((uint32_t)src[0] << 24) |
           ((uint32_t)src[1] << 16) |
           ((uint32_t)src[2] << 8)  |
           ((uint32_t)src[3]);
}

// --- VM INSTRUCTION DECODING ---

enum OperandType { OP_REG, OP_MEM, OP_LIT, OP_SP1, OP_SP2 };

struct DecodedInstr {
    uint8_t opcode_type; // 0 = Op3, 1 = Op2
    uint8_t op_code;     // Specific op
    uint8_t op1_type;
    uint8_t op2_type;
    uint8_t r1;
    uint8_t r2;
    uint8_t r3;
    uint64_t lit1;
    uint64_t lit2;
};

__device__ DecodedInstr decode_instruction_from_stream(Blake2bStream* stream) {
    DecodedInstr d;
    uint8_t instr[20];
    blake2b_stream_fill(stream, instr, 20);

    uint8_t val = instr[0];
    
    // Decode Opcode
    if (val < 40) { d.opcode_type = 0; d.op_code = 0; } // Add
    else if (val < 80) { d.opcode_type = 0; d.op_code = 1; } // Mul
    else if (val < 96) { d.opcode_type = 0; d.op_code = 2; } // MulH
    else if (val < 112) { d.opcode_type = 0; d.op_code = 3; } // Div
    else if (val < 128) { d.opcode_type = 0; d.op_code = 4; } // Mod
    else if (val < 138) { d.opcode_type = 1; d.op_code = 0; } // ISqrt
    else if (val < 148) { d.opcode_type = 1; d.op_code = 2; } // BitRev
    else if (val < 188) { d.opcode_type = 0; d.op_code = 5; } // Xor
    else if (val < 204) { d.opcode_type = 1; d.op_code = 3; } // RotL
    else if (val < 220) { d.opcode_type = 1; d.op_code = 4; } // RotR
    else if (val < 240) { d.opcode_type = 1; d.op_code = 1; } // Neg
    else if (val < 248) { d.opcode_type = 0; d.op_code = 6; } // And
    else { d.opcode_type = 0; d.op_code = 7 + (val - 248); } // Hash

    // Decode Operands
    uint8_t ops = instr[1];
    
    auto get_op_type = [](uint8_t v) {
        if (v < 5) return OP_REG;
        if (v < 9) return OP_MEM;
        if (v < 13) return OP_LIT;
        if (v < 14) return OP_SP1;
        return OP_SP2;
    };
    
    d.op1_type = get_op_type(ops >> 4);
    d.op2_type = get_op_type(ops & 0x0F);
    
    // Registers
    uint16_t rs = ((uint16_t)instr[2] << 8) | (uint16_t)instr[3];
    d.r1 = ((rs >> 10) & 0x1F);
    d.r2 = ((rs >> 5) & 0x1F);
    d.r3 = (rs & 0x1F);
    
    // Literals
    d.lit1 = 0; d.lit2 = 0;
    for(int i=0; i<8; i++) d.lit1 |= ((uint64_t)instr[4+i]) << (i*8);
    for(int i=0; i<8; i++) d.lit2 |= ((uint64_t)instr[12+i]) << (i*8);
    
    return d;
}

// --- KERNEL ENTRY ---

extern "C" {

__global__ void mine_kernel_v2(
    const uint8_t* rom,
    int rom_len_bytes,
    const uint8_t* rom_digest_ptr,
    const uint8_t* salt_prefixes, // Flat array: [salt_len * gridDim.y]
    int salt_len,
    const uint64_t* start_nonces, // Array: [gridDim.y]
    const uint64_t* difficulties, // Array: [gridDim.y]
    uint64_t* found_nonce,
    int* found_flag
) {
    // Batching: blockIdx.y determines which wallet/task we are working on
    int task_idx = blockIdx.y;
    
    // Calculate pointers for this task
    const uint8_t* my_salt_prefix = salt_prefixes + (task_idx * salt_len);
    uint64_t my_start_nonce = start_nonces[task_idx];
    uint64_t my_difficulty = difficulties[task_idx];
    
    uint64_t idx = blockIdx.x * blockDim.x + threadIdx.x;
    uint64_t nonce = my_start_nonce + idx;
    
    // Local Registers
    uint64_t regs[NB_REGS];
    Blake2bCtx prog_digest_ctx;
    Blake2bCtx mem_digest_ctx;
    uint8_t prog_seed[64];
    uint32_t memory_counter = 0;
    uint32_t loop_counter = 0;
    uint32_t ip = 0;
    uint64_t cached_prog_digest_word = 0;
    uint64_t cached_mem_digest_word = 0;
    bool prog_digest_word_valid = false;
    bool mem_digest_word_valid = false;

    // 1. Initialization
    auto to_hex = [](uint8_t v) -> uint8_t {
        return (v < 10) ? (v + '0') : (v - 10 + 'a');
    };
    
    uint8_t nonce_hex[16];
    for(int i=0; i<8; i++) {
        uint8_t byte_val = (nonce >> ((7-i)*8)) & 0xFF;
        nonce_hex[2*i]     = to_hex(byte_val >> 4);
        nonce_hex[2*i + 1] = to_hex(byte_val & 0x0F);
    }

    Blake2bCtx ctx;
    uint8_t V[64];
    blake2b_init(&ctx, 64);
    uint32_t out_len_le = 448;
    blake2b_update(&ctx, &out_len_le, 4);
    blake2b_update(&ctx, rom_digest_ptr, 64);
    blake2b_update(&ctx, nonce_hex, 16);
    blake2b_update(&ctx, my_salt_prefix, salt_len);
    blake2b_final(&ctx, V);

    uint8_t digest1[64];
    uint8_t digest2[64];
    int bytes_written = 0;
    
    // Argon2 H' Expansion (fill 448 bytes)
    uint8_t temp_V[64];
    for(int i=0; i<64; i++) temp_V[i] = V[i];
    
    for(int r=1; r<=13; r++) {
        int copy_len = (r == 13) ? 64 : 32;
        for(int k=0; k<copy_len; k++) {
            if(bytes_written < 256) {
                ((uint8_t*)regs)[bytes_written] = temp_V[k];
            } else if(bytes_written < 320) {
                digest1[bytes_written - 256] = temp_V[k];
            } else if(bytes_written < 384) {
                digest2[bytes_written - 320] = temp_V[k];
            } else {
                prog_seed[bytes_written - 384] = temp_V[k];
            }
            bytes_written++;
        }
        
        if(r < 13) {
            Blake2bCtx next_ctx;
            blake2b_init(&next_ctx, 64);
            blake2b_update(&next_ctx, temp_V, 64);
            blake2b_final(&next_ctx, temp_V);
        }
    }

    blake2b_init(&prog_digest_ctx, 64);
    blake2b_update(&prog_digest_ctx, digest1, 64);
    prog_digest_word_valid = false;
    blake2b_init(&mem_digest_ctx, 64);
    blake2b_update(&mem_digest_ctx, digest2, 64);
    mem_digest_word_valid = false;
    
    // --- Main Loop ---
    
    for(int loop=0; loop<8; loop++) {
        // Initialize instruction stream
        Blake2bStream instr_stream;
        blake2b_stream_init(&instr_stream, INSTR_SIZE * 256, prog_seed);

        for(int instr_idx=0; instr_idx<256; instr_idx++) {
            // Decode instruction directly from stream
            // We need to capture bytes for the digest update
            uint8_t instr_bytes[20];
            // Peek/Fill logic:
            // We can use blake2b_stream_fill to get bytes into a local buffer
            // This uses 20 bytes of registers/local mem, which is fine.
            blake2b_stream_fill(&instr_stream, instr_bytes, 20);
            
            // We need to decode from these bytes
            // Re-implement decode to use the buffer
            DecodedInstr op;
            {
                uint8_t val = instr_bytes[0];
                if (val < 40) { op.opcode_type = 0; op.op_code = 0; }
                else if (val < 80) { op.opcode_type = 0; op.op_code = 1; }
                else if (val < 96) { op.opcode_type = 0; op.op_code = 2; }
                else if (val < 112) { op.opcode_type = 0; op.op_code = 3; }
                else if (val < 128) { op.opcode_type = 0; op.op_code = 4; }
                else if (val < 138) { op.opcode_type = 1; op.op_code = 0; }
                else if (val < 148) { op.opcode_type = 1; op.op_code = 2; }
                else if (val < 188) { op.opcode_type = 0; op.op_code = 5; }
                else if (val < 204) { op.opcode_type = 1; op.op_code = 3; }
                else if (val < 220) { op.opcode_type = 1; op.op_code = 4; }
                else if (val < 240) { op.opcode_type = 1; op.op_code = 1; }
                else if (val < 248) { op.opcode_type = 0; op.op_code = 6; }
                else { op.opcode_type = 0; op.op_code = 7 + (val - 248); }

                uint8_t ops = instr_bytes[1];
                auto get_op_type = [](uint8_t v) {
                    if (v < 5) return OP_REG;
                    if (v < 9) return OP_MEM;
                    if (v < 13) return OP_LIT;
                    if (v < 14) return OP_SP1;
                    return OP_SP2;
                };
                op.op1_type = get_op_type(ops >> 4);
                op.op2_type = get_op_type(ops & 0x0F);
                
                uint16_t rs = ((uint16_t)instr_bytes[2] << 8) | (uint16_t)instr_bytes[3];
                op.r1 = ((rs >> 10) & 0x1F);
                op.r2 = ((rs >> 5) & 0x1F);
                op.r3 = (rs & 0x1F);
                
                op.lit1 = 0; op.lit2 = 0;
                for(int i=0; i<8; i++) op.lit1 |= ((uint64_t)instr_bytes[4+i]) << (i*8);
                for(int i=0; i<8; i++) op.lit2 |= ((uint64_t)instr_bytes[12+i]) << (i*8);
            }
            
            uint64_t src1 = 0, src2 = 0;
            
            auto fetch_val = [&](uint8_t type, uint8_t reg_idx, uint64_t lit) -> uint64_t {
                if(type == OP_REG) return regs[reg_idx & 0x1F];
                if(type == OP_LIT) return lit;
                if(type == OP_SP1) {
                     if (!prog_digest_word_valid) {
                         Blake2bCtx temp = prog_digest_ctx;
                         uint8_t res[64];
                         blake2b_final(&temp, res);
                         cached_prog_digest_word = load_le_u64(res);
                         prog_digest_word_valid = true;
                     }
                     return cached_prog_digest_word;
                }
                if(type == OP_SP2) {
                     if (!mem_digest_word_valid) {
                         Blake2bCtx temp = mem_digest_ctx;
                         uint8_t res[64];
                         blake2b_final(&temp, res);
                         cached_mem_digest_word = load_le_u64(res);
                         mem_digest_word_valid = true;
                     }
                     return cached_mem_digest_word;
                }
                if(type == OP_MEM) {
                    uint32_t chunk_count = (uint32_t)(rom_len_bytes / ROM_ACCESS_SIZE);
                    if (chunk_count == 0) return 0;
                    
                    uint32_t chunk_idx = (uint32_t)(lit % (uint64_t)chunk_count);
                    uint64_t offset = (uint64_t)chunk_idx;

                    const uint8_t* mem_ptr = rom + offset;
                    
                    blake2b_update(&mem_digest_ctx, mem_ptr, 64);
                    mem_digest_word_valid = false;
                    
                    uint32_t new_counter = memory_counter + 1;
                    uint32_t byte_idx = (new_counter % 8) * 8;
                    memory_counter = new_counter;
                    
                    uint64_t val = 0;
                    for(int i=0; i<8; i++) val |= ((uint64_t)mem_ptr[byte_idx+i]) << (i*8);
                    return val;
                }
                return 0;
            };

            src1 = fetch_val(op.op1_type, op.r1, op.lit1);
            
            if (op.opcode_type == 0) { // Op3 uses src2
                 src2 = fetch_val(op.op2_type, op.r2, op.lit2);
            }

            // Execute Operation
            uint64_t result = 0;
            if (op.opcode_type == 0) { // Op3
                switch(op.op_code) {
                    case 0: result = src1 + src2; break; // Add
                    case 1: result = src1 * src2; break; // Mul
                    case 2: // MulH
                        asm("mul.hi.u64 %0, %1, %2;" : "=l"(result) : "l"(src1), "l"(src2));
                        break;
                    case 3: result = (src2 == 0) ? fetch_val(OP_SP1, 0, 0) : (src1 / src2); break; // Div
                    case 4: // Mod
                        result = (src2 == 0)
                            ? fetch_val(OP_SP1, 0, 0)
                            : (src1 / src2);
                        break;
                    case 5: result = src1 ^ src2; break; // Xor
                    case 6: result = src1 & src2; break; // And
                    default: // Hash(v)
                        {
                            uint8_t v = op.op_code - 7;
                            Blake2bCtx hctx;
                            blake2b_init(&hctx, 64);
                            blake2b_update(&hctx, &src1, 8);
                            blake2b_update(&hctx, &src2, 8);
                            uint8_t hres[64];
                            blake2b_final(&hctx, hres);
                            int offset = v * 8;
                            result = 0;
                            for(int i=0; i<8; i++) result |= ((uint64_t)hres[offset+i]) << (i*8);
                        }
                        break;
                }
                regs[op.r3] = result;
            } else { // Op2
                 switch(op.op_code) {
                     case 0: result = isqrt(src1); break;
                     case 1: result = ~src1; break; // Neg
                     case 2: result = bit_rev(src1); break;
                     case 3: result = (src1 << op.r1) | (src1 >> ((64 - op.r1) & 63)); break; // RotL
                     case 4: result = (src1 >> op.r1) | (src1 << ((64 - op.r1) & 63)); break; // RotR
                 }
                 regs[op.r3] = result;
            }
            
            blake2b_update(&prog_digest_ctx, instr_bytes, 20);
            prog_digest_word_valid = false;
            ip++;

        } // End instructions
        
        uint64_t sum_regs = 0;
        for(int i=0; i<NB_REGS; i++) sum_regs += regs[i];

        // prog_value = hash(prog_digest || sum_regs)
        Blake2bCtx pv_ctx = prog_digest_ctx; // Clone state
        blake2b_update(&pv_ctx, &sum_regs, 8);
        uint8_t prog_value[64];
        blake2b_final(&pv_ctx, prog_value);
        
        // mem_value = hash(mem_digest || sum_regs)
        Blake2bCtx mv_ctx = mem_digest_ctx;
        blake2b_update(&mv_ctx, &sum_regs, 8);
        uint8_t mem_value[64];
        blake2b_final(&mv_ctx, mem_value);
        
        // mixing_value = hash(prog_value || mem_value || loop_counter)
        Blake2bCtx mix_ctx;
        blake2b_init(&mix_ctx, 64);
        blake2b_update(&mix_ctx, prog_value, 64);
        blake2b_update(&mix_ctx, mem_value, 64);
        blake2b_update(&mix_ctx, &loop_counter, 4);
        uint8_t mixing_value[64];
        blake2b_final(&mix_ctx, mixing_value);
        
        // Stream mixing bytes
        Blake2bStream mix_stream;
        blake2b_stream_init(&mix_stream, MIX_STREAM_BYTES, mixing_value);
        
        for(int chunk=0; chunk<32; chunk++) {
            for(int r=0; r<NB_REGS; r++) {
                uint64_t mix_u64 = 0;
                // Read 8 bytes from stream
                for(int b=0; b<8; b++) {
                    mix_u64 |= ((uint64_t)blake2b_stream_next(&mix_stream)) << (b * 8);
                }
                regs[r] ^= mix_u64;
            }
        }
        
        // Update state
        for(int i=0; i<64; i++) prog_seed[i] = prog_value[i];
        loop_counter++;

    } // End loop
    
    // Finalize
    uint8_t final_prog[64];
    blake2b_final(&prog_digest_ctx, final_prog);
    uint8_t final_mem[64];
    blake2b_final(&mem_digest_ctx, final_mem);
    
    Blake2bCtx final_ctx;
    blake2b_init(&final_ctx, 64);
    blake2b_update(&final_ctx, final_prog, 64);
    blake2b_update(&final_ctx, final_mem, 64);
    blake2b_update(&final_ctx, &memory_counter, 4);
    blake2b_update(&final_ctx, regs, NB_REGS * 8);
    
    uint8_t result_hash[64];
    blake2b_final(&final_ctx, result_hash);
    
    uint32_t hash_prefix = load_be_u32(result_hash);
    uint32_t difficulty_prefix = (uint32_t)(my_difficulty & 0xFFFFFFFFULL);
    
    if (((hash_prefix | difficulty_prefix) == difficulty_prefix) &&
        atomicCAS(found_flag, 0, 1) == 0) {
        *found_nonce = nonce;
    }
}

}
"""
