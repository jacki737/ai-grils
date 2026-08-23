from xdis import disassemble_file
import sys

# 逐个导出关键函数的反汇编
# disassemble_file 支持 methods 参数指定函数名

key_functions = [
    'chat',           # 主聊天逻辑 line 845
    '_run_tool_loop', # 后台工具循环 line 700
    '_pre_force_open',# 打开应用预处理 line 761
    '_try_force_open_app',
    'get_history',    # 历史端点 line 579
    'persona',        # 单人设端点 line 587
    'list_personas',  # 列表端点 line 597
    'create_persona', # 创建人设 line 603
    'remove_persona', # 删除人设 line 622
    'get_settings',   # 设置端点 line 657
    'update_settings',# 更新设置 line 669
    'load_personas',  # 加载人设 line 68
    'save_persona',   # 保存人设 line 86
    'resolve_persona',# 解析人设 line 140
    'load_role_history', 'save_role_history',
    '_history_summary',  # 记忆摘要 line 188
    'stt',            # 语音识别 line 1121
    'tts',            # 语音合成 line 1236
    'xiaoai_tts',     # 小爱TTS line 1169
    'cosyvoice_synthesize', # CosyVoice line 1197
    'call_deepseek',  # DeepSeek 调用 line 285
    '_extract_text_toolcalls', # 工具调用提取 line 431
    'clean_reply',    # 回复清洗 line 264
    'task_status', 'reset',
    'mimo_asr_transcribe', 'whisper_transcribe', 'paraformer_transcribe',
    '_decode_audio',
    'get_whisper_model',
]

# 写入单独文件
for fn in key_functions:
    out_path = f"E:\\ai-girlfriend\\disasm_{fn}.txt"
    with open(out_path, "w", encoding="utf-8") as out_f:
        disassemble_file(
            r"E:\ai-girlfriend\__pycache__\app.cpython-310.pyc",
            outstream=out_f,
            methods=(fn,),
            show_source=True
        )
    print(f"Exported {fn} -> {out_path}")

print("All done")