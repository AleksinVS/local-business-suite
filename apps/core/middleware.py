import logging

logger = logging.getLogger("apps.core.iis_path_debug")


class PathInfoDebugMiddleware:
    """Фикс PATH_INFO для IIS/FastCGI (wfastcgi искажает PATH_INFO в "/").

    Подключается в ``MIDDLEWARE`` только когда ``LOCAL_BUSINESS_IIS_COMPAT_ENABLED=true``
    (см. ``config/settings.py:build_middleware``) — на Linux/Docker-развёртываниях
    без IIS этот middleware вообще не участвует в обработке запроса. Сама эвристика
    исправления PATH_INFO ниже не менялась и специфична для IIS/FastCGI, не для
    других веб-серверов.

    Диагностический лог пишется штатным ``logging`` (не через ``open()``) в
    ``DATA_DIR/logs/iis_path_debug.log`` — см. ``LOGGING["loggers"]["apps.core.iis_path_debug"]``
    в ``config/settings.py``. По умолчанию уровень этого логгера — WARNING, а запись
    ниже идёт на уровне INFO, поэтому по умолчанию ничего не пишется и файл не
    создаётся (у обработчика ``delay=True``). Подробный лог включается уровнем
    логгера через ``LOCAL_BUSINESS_IIS_PATH_DEBUG_LOG_LEVEL=INFO`` (или ``DEBUG``).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Fix IIS PATH_INFO issue - only apply if there's a clear mismatch
        request_uri = request.META.get("REQUEST_URI", "")
        path_info = request.META.get("PATH_INFO", "")

        # Only fix if PATH_INFO is clearly wrong:
        # 1. PATH_INFO is just '/'
        # 2. REQUEST_URI has a different path (not '/')
        # 3. REQUEST_URI is not empty
        # 4. We're not dealing with favicon (favicon остаётся на IIS/404)
        #
        # /static/ намеренно НЕ исключаем: при раздаче статики через
        # WhiteNoise (FastCGI-хендлер в web.config для /static/) PATH_INFO для
        # статик-путей тоже искажается в "/", и его нужно починить — иначе
        # WhiteNoise (стоит в MIDDLEWARE правее этого фикса) не опознаёт путь
        # и не отдаёт файлы, в т.ч. стили Django admin.
        if (
            path_info == "/"
            and request_uri != "/"
            and request_uri
            and not request_uri.startswith("/favicon.")
        ):
            # Extract path from REQUEST_URI (remove query string)
            path = request_uri.split("?")[0]

            # Only fix if the extracted path is valid
            if path and path.startswith("/"):
                # Update PATH_INFO and SCRIPT_NAME
                request.META["PATH_INFO"] = path
                request.META["SCRIPT_NAME"] = ""
                # Rebuild request.path
                request.path = path
                request.path_info = path

        logger.info(
            "Path: %s | Path Info: %s | SCRIPT_NAME: %s | PATH_INFO: %s | REQUEST_URI: %s",
            request.path,
            request.path_info,
            request.META.get("SCRIPT_NAME", ""),
            request.META.get("PATH_INFO"),
            request.META.get("REQUEST_URI"),
        )

        response = self.get_response(request)
        return response
