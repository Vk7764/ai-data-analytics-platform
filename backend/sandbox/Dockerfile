FROM python:3.11-slim

RUN pip install --no-cache-dir pandas numpy

COPY runner.py /runner.py

# Run as an unprivileged user with no writable bytecode cache.
RUN useradd --no-create-home --uid 10001 --shell /usr/sbin/nologin sandbox
ENV PYTHONDONTWRITEBYTECODE=1
USER sandbox

CMD ["python", "/runner.py"]