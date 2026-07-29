import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { filesApi } from "../../shared/api/client";
import type { UploadSummary, UploadTask } from "../../shared/api/types";

const MAX_CONCURRENT_UPLOADS = 3;
let nextTaskId = 0;

interface ManagedUploadTask extends UploadTask {
  generation: number;
  hostId: string;
}

function uploadError(error: unknown): string {
  return error instanceof Error ? error.message : "Upload failed";
}

function destinationPath(directory: string, filename: string): string {
  return `${directory === "/" ? "" : directory.replace(/\/+$/, "")}/${filename}`;
}

export function useUploadQueue(hostId: string, onCompleted: () => void) {
  const [managedTasks, setManagedTasks] = useState<ManagedUploadTask[]>([]);
  const activeRef = useRef(new Map<string, AbortController>());
  const generationRef = useRef(0);
  const mountedRef = useRef(true);
  const previousHostRef = useRef(hostId);
  const onCompletedRef = useRef(onCompleted);
  onCompletedRef.current = onCompleted;

  useEffect(() => {
    mountedRef.current = true;
    const active = activeRef.current;
    return () => {
      mountedRef.current = false;
      generationRef.current += 1;
      active.forEach((controller) => controller.abort());
      active.clear();
    };
  }, []);

  useEffect(() => {
    if (previousHostRef.current === hostId) return;

    previousHostRef.current = hostId;
    generationRef.current += 1;
    activeRef.current.forEach((controller) => controller.abort());
    activeRef.current.clear();
    setManagedTasks((current) =>
      current.map((task) =>
        task.status === "queued" || task.status === "uploading"
          ? { ...task, status: "cancelled" }
          : task
      )
    );
  }, [hostId]);

  useEffect(() => {
    const available = MAX_CONCURRENT_UPLOADS - activeRef.current.size;
    if (available <= 0) return;

    const generation = generationRef.current;
    const next = managedTasks
      .filter(
        (task) =>
          task.status === "queued" &&
          task.hostId === hostId &&
          task.generation === generation &&
          !activeRef.current.has(task.id)
      )
      .slice(0, available);
    if (!next.length) return;

    for (const task of next) {
      activeRef.current.set(task.id, new AbortController());
    }
    const startingIds = new Set(next.map((task) => task.id));
    setManagedTasks((current) =>
      current.map((task) =>
        startingIds.has(task.id) && task.status === "queued"
          ? { ...task, status: "uploading" }
          : task
      )
    );

    for (const task of next) {
      const controller = activeRef.current.get(task.id);
      if (!controller) continue;

      void filesApi
        .upload(task.hostId, task.destination, task.file, {
          signal: controller.signal,
          onProgress: ({ loaded, total }) => {
            if (
              !mountedRef.current ||
              controller.signal.aborted ||
              generationRef.current !== task.generation
            ) {
              return;
            }
            setManagedTasks((current) =>
              current.map((item) =>
                item.id === task.id
                  ? { ...item, loaded, total: total ?? item.total }
                  : item
              )
            );
          }
        })
        .then(() => {
          if (
            !mountedRef.current ||
            controller.signal.aborted ||
            generationRef.current !== task.generation
          ) {
            return;
          }
          activeRef.current.delete(task.id);
          setManagedTasks((current) =>
            current.map((item) =>
              item.id === task.id
                ? { ...item, loaded: item.total, status: "completed" }
                : item
            )
          );
          onCompletedRef.current();
        })
        .catch((error: unknown) => {
          if (!mountedRef.current || generationRef.current !== task.generation) return;

          activeRef.current.delete(task.id);
          setManagedTasks((current) =>
            current.map((item) =>
              item.id === task.id
                ? controller.signal.aborted
                  ? { ...item, status: "cancelled" }
                  : { ...item, status: "failed", error: uploadError(error) }
                : item
            )
          );
        });
    }
  }, [hostId, managedTasks]);

  const enqueue = useCallback(
    (files: File[] | FileList, directory: string) => {
      const generation = generationRef.current;
      const additions = Array.from(files).map<ManagedUploadTask>((file) => ({
        id: `upload-${Date.now()}-${++nextTaskId}`,
        file,
        destination: destinationPath(directory, file.name),
        loaded: 0,
        total: file.size,
        status: "queued",
        generation,
        hostId
      }));
      if (additions.length) setManagedTasks((current) => [...current, ...additions]);
    },
    [hostId]
  );

  const cancel = useCallback((id: string) => {
    const controller = activeRef.current.get(id);
    if (controller) {
      controller.abort();
      activeRef.current.delete(id);
    }
    setManagedTasks((current) =>
      current.map((task) =>
        task.id === id && (task.status === "queued" || task.status === "uploading")
          ? { ...task, status: "cancelled" }
          : task
      )
    );
  }, []);

  const cancelAll = useCallback(() => {
    generationRef.current += 1;
    activeRef.current.forEach((controller) => controller.abort());
    activeRef.current.clear();
    setManagedTasks((current) =>
      current.map((task) =>
        task.status === "queued" || task.status === "uploading"
          ? { ...task, status: "cancelled" }
          : task
      )
    );
  }, []);

  const tasks: UploadTask[] = managedTasks;
  const summary = useMemo<UploadSummary>(() => {
    const totalBytes = tasks.reduce((total, task) => total + task.total, 0);
    const loaded = tasks.reduce((total, task) => total + Math.min(task.loaded, task.total), 0);
    const allCompleted = tasks.length > 0 && tasks.every((task) => task.status === "completed");
    return {
      total: tasks.length,
      queued: tasks.filter((task) => task.status === "queued").length,
      uploading: tasks.filter((task) => task.status === "uploading").length,
      completed: tasks.filter((task) => task.status === "completed").length,
      failed: tasks.filter((task) => task.status === "failed").length,
      cancelled: tasks.filter((task) => task.status === "cancelled").length,
      loaded,
      totalBytes,
      percent: totalBytes ? Math.round((loaded / totalBytes) * 100) : allCompleted ? 100 : 0
    };
  }, [tasks]);

  return { enqueue, cancel, cancelAll, tasks, summary };
}
