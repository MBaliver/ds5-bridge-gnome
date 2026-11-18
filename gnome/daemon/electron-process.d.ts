// Upstream backend reads Electron's process.resourcesPath; the daemon sets it.
declare namespace NodeJS {
  interface Process {
    resourcesPath: string;
  }
}
