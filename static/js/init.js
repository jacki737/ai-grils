// ===== 初始化调用(依赖上面所有模块加载完毕) =====
// Live2D 立绘初始化(延迟到布局完成后)
setTimeout(initLive2D, 100);
// 保留角色历史, 刷新页面不重置记忆(记忆持久化)
fetch('/api/history?role=' + encodeURIComponent(currentRole)).catch(() => {});
// 打开页面自动进入持续语音通话模式（电话风格）
setTimeout(startVoiceMode, 800);