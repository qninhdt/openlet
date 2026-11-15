FROM node:26.13.0-slim@sha256:5adad64f9a1fca2d51972caa65983634c8a774eb300d72b20f7f2a0f60368072 AS dependencies
WORKDIR /work
RUN npm install --global pnpm@12.18.0
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY e2e/package.json e2e/package.json
RUN --mount=type=cache,target=/root/.local/share/pnpm/store pnpm install --frozen-lockfile

FROM dependencies AS api
COPY e2e e2e
WORKDIR /work/e2e
ENV PLAYWRIGHT_OUTPUT_DIR=/results/traces PLAYWRIGHT_JUNIT_OUTPUT_FILE=/results/junit.xml PLAYWRIGHT_HTML_OUTPUT_DIR=/results/html
ENTRYPOINT ["pnpm", "exec", "playwright"]
CMD ["test", "--project=api"]
