#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Jetson GPU 压测 / 基准。

用大矩阵乘把 GPU 打满（fp16 走张量核，实测 ~6.2 TFLOPS；fp32 ~1.0 TFLOPS），
边跑边采样频率、占用、温度、功耗，写成 JSON 供网页轮询。

为什么不用 tegrastats 取指标：整机只能有一个 tegrastats 实例，
jetson_agent 已经占着了，再起一个会互相打架。所以这里直接读 sysfs。

    python3 gpu_bench.py --seconds 60 --size 4096 --dtype fp16
    touch ~/gpu_bench.stop      # 提前停

状态写到 GPU_BENCH_STATUS（默认 ~/gpu_bench_status.json）。
"""
import argparse, glob, json, os, tempfile, time

STATUS = os.environ.get('GPU_BENCH_STATUS') or os.path.expanduser('~/gpu_bench_status.json')
STOP = os.environ.get('GPU_BENCH_STOP') or os.path.expanduser('~/gpu_bench.stop')

GPU_LOAD = '/sys/devices/platform/17000000.gpu/load'              # 千分比
GPU_FREQ = '/sys/devices/platform/17000000.gpu/devfreq_dev/cur_freq'
GPU_FMAX = '/sys/devices/platform/17000000.gpu/devfreq_dev/max_freq'
THERMAL = '/sys/devices/virtual/thermal'
INA_GLOB = '/sys/bus/i2c/drivers/ina3221'


def _read(p, default=None):
    try:
        with open(p) as f:
            return f.read().strip()
    except Exception:
        return default


def _int(p, default=0):
    v = _read(p)
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def temps():
    out = {}
    base = os.path.join(THERMAL)
    try:
        zones = [z for z in os.listdir(base) if z.startswith('thermal_zone')]
    except OSError:
        return out
    for z in zones:
        t = _read(os.path.join(base, z, 'type'))
        v = _read(os.path.join(base, z, 'temp'))
        if t and v:
            try:
                out[t] = round(int(v) / 1000.0, 1)
            except ValueError:
                pass
    return out


def power_w():
    """ina3221 给的是电压(mV)和电流(mA)，自己乘出瓦数。
    注意用 glob 不能用 os.walk：/sys/bus/i2c/drivers/ina3221/1-0040 是符号链接，
    os.walk 默认不跟随，走出来是空的。"""
    out = {}
    for h in glob.glob(INA_GLOB + '/*/hwmon/hwmon*'):
        for i in (1, 2, 3):
            lab = _read(os.path.join(h, 'in%d_label' % i))
            if not lab:
                continue
            mv = _int(os.path.join(h, 'in%d_input' % i))
            ma = _int(os.path.join(h, 'curr%d_input' % i))
            out[lab] = round(mv * ma / 1e6, 2)
    return out


def write_status(d):
    tmp = tempfile.mktemp(dir=os.path.dirname(STATUS) or '.', prefix='.gpub.')
    with open(tmp, 'w') as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, STATUS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seconds', type=float, default=60)
    ap.add_argument('--size', type=int, default=4096)
    ap.add_argument('--dtype', choices=['fp16', 'fp32'], default='fp16')
    ap.add_argument('--max-temp', type=float, default=92.0)
    a = ap.parse_args()

    if os.path.exists(STOP):
        os.remove(STOP)
    st = {'state': 'starting', 'seconds': a.seconds, 'size': a.size, 'dtype': a.dtype,
          'started': time.time(), 'elapsed': 0, 'pct': 0, 'samples': [], 'note': ''}
    write_status(st)

    try:
        import torch
    except Exception as e:
        st.update(state='error', note='导入 torch 失败: %s' % e)
        return write_status(st)
    if not torch.cuda.is_available():
        st.update(state='error', note='torch 看不到 CUDA 设备')
        return write_status(st)

    dt = torch.float16 if a.dtype == 'fp16' else torch.float32
    n = a.size
    dev = 'cuda'
    st['device'] = torch.cuda.get_device_name(0)
    st['gpu_mhz_max'] = _int(GPU_FMAX) // 1000000

    try:
        x = torch.randn(n, n, device=dev, dtype=dt)
        y = torch.randn(n, n, device=dev, dtype=dt)
    except Exception as e:
        st.update(state='error', note='分配显存失败（矩阵太大？）: %s' % e)
        return write_status(st)

    for _ in range(3):            # 预热，避免把首次 kernel 编译算进成绩
        z = x @ y
    torch.cuda.synchronize()

    t0 = time.time()
    win_t, win_it = t0, 0
    total_it = 0
    peak = 0.0
    st['state'] = 'running'
    flop_per_it = 2.0 * n ** 3

    while True:
        z = x @ y
        # 每次都同步：CUDA 是异步的，不同步的话 0.5 秒内能把上千个 kernel 排进队列，
        # 之后 synchronize() 一等十几秒，采样窗口和进度全失真（实测 12 秒只采到 1 个点）。
        # 单次 matmul 就有 20ms 量级，每次同步的开销可以忽略。
        torch.cuda.synchronize()
        win_it += 1
        total_it += 1
        now = time.time()
        if now - win_t < 0.5:
            continue
        gf = flop_per_it * win_it / (now - win_t) / 1e9
        peak = max(peak, gf)
        el = now - t0
        tp = temps()
        tmax = max(tp.values()) if tp else 0
        pw = power_w()
        sample = {'t': round(el, 1), 'gflops': round(gf, 1),
                  'load': _int(GPU_LOAD) / 10.0, 'mhz': _int(GPU_FREQ) // 1000000,
                  'temp': tmax, 'w': pw.get('VDD_IN', 0)}
        st['samples'].append(sample)
        st['samples'] = st['samples'][-600:]      # 最多留 5 分钟，别让文件无限长
        st.update(elapsed=round(el, 1), pct=min(100, round(el / a.seconds * 100, 1)),
                  gflops=round(gf, 1), gflops_peak=round(peak, 1),
                  gflops_avg=round(flop_per_it * total_it / el / 1e9, 1),
                  gpu_load=sample['load'], gpu_mhz=sample['mhz'],
                  temps=tp, temp_max=tmax, power=pw)
        write_status(st)
        win_t, win_it = now, 0

        if tmax >= a.max_temp:
            st.update(state='aborted', note='温度 %.1f°C 达到上限 %.1f°C，已停止' % (tmax, a.max_temp))
            break
        if os.path.exists(STOP):
            os.remove(STOP)
            st.update(state='stopped', note='手动停止')
            break
        if el >= a.seconds:
            st.update(state='done', pct=100, note='完成')
            break

    del x, y, z
    torch.cuda.empty_cache()
    write_status(st)


if __name__ == '__main__':
    main()
