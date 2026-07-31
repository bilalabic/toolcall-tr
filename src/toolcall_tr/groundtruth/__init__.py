"""Ground-truth üretimi — Faz A (planner) ve Faz B (runner).

``planner``  : Blueprint -> CallPlan. Saf, I/O yok. Gerçek derleyici budur.
``runner``   : CallPlan x Environment -> Trace. I/O var, seed altında deterministik.

Bu ikisi kasıtlı olarak ayrıdır: referans çözümü çalıştırma gerektirdiği için
tek bir "compile" fonksiyonu yan etkili olurdu.
"""
