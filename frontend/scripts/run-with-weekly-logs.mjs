import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { spawn } from "node:child_process";

function currentWeekStamp() {
  const now = new Date();
  const utcDate = new Date(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()));
  const day = utcDate.getUTCDay() || 7;
  utcDate.setUTCDate(utcDate.getUTCDate() + 4 - day);
  const yearStart = new Date(Date.UTC(utcDate.getUTCFullYear(), 0, 1));
  const week = Math.ceil((((utcDate - yearStart) / 86400000) + 1) / 7);
  return `${utcDate.getUTCFullYear()}-W${String(week).padStart(2, "0")}`;
}

class WeeklyLogWriter {
  constructor(logDir, logName, keepWeeks) {
    this.logDir = logDir;
    this.logName = logName;
    this.keepWeeks = keepWeeks;
    this.currentStamp = null;
    this.stream = null;
  }

  currentPath() {
    return path.join(this.logDir, `${this.logName}-${currentWeekStamp()}.log`);
  }

  ensureStream() {
    const stamp = currentWeekStamp();
    if (this.stream && this.currentStamp === stamp) {
      return;
    }

    fs.mkdirSync(this.logDir, { recursive: true });
    if (this.stream) {
      this.stream.end();
    }

    this.currentStamp = stamp;
    this.stream = fs.createWriteStream(this.currentPath(), { flags: "a" });
    this.cleanup();
  }

  cleanup() {
    const entries = fs
      .readdirSync(this.logDir)
      .filter((entry) => entry.startsWith(`${this.logName}-`) && entry.endsWith(".log"))
      .sort()
      .reverse();

    for (const entry of entries.slice(this.keepWeeks)) {
      fs.rmSync(path.join(this.logDir, entry), { force: true });
    }
  }

  write(chunk) {
    if (!chunk || chunk.length === 0) {
      return;
    }

    this.ensureStream();
    this.stream.write(chunk);
  }

  close() {
    if (this.stream) {
      this.stream.end();
      this.stream = null;
    }
  }
}

function parseArgs(argv) {
  const args = [...argv];
  const result = {
    logDir: "./logs",
    logName: "frontend",
    keepWeeks: 12,
    command: [],
  };

  while (args.length > 0) {
    const current = args.shift();
    if (current === "--") {
      result.command = args;
      break;
    }
    if (current === "--log-dir") {
      result.logDir = args.shift();
      continue;
    }
    if (current === "--log-name") {
      result.logName = args.shift();
      continue;
    }
    if (current === "--keep-weeks") {
      result.keepWeeks = Number(args.shift() || "12");
      continue;
    }
    throw new Error(`Unknown argument: ${current}`);
  }

  if (result.command.length === 0) {
    throw new Error("Command is required after --");
  }

  return result;
}

const options = parseArgs(process.argv.slice(2));
const writer = new WeeklyLogWriter(path.resolve(process.cwd(), options.logDir), options.logName, options.keepWeeks);
const [command, ...commandArgs] = options.command;

const child = spawn(command, commandArgs, {
  cwd: process.cwd(),
  env: process.env,
  stdio: ["inherit", "pipe", "pipe"],
});

child.stdout.on("data", (chunk) => {
  process.stdout.write(chunk);
  writer.write(chunk);
});

child.stderr.on("data", (chunk) => {
  process.stderr.write(chunk);
  writer.write(chunk);
});

const closeAndExit = (code, signal) => {
  writer.close();
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 0);
};

child.on("close", closeAndExit);

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => {
    child.kill(signal);
  });
}
