import threading
import time

from app.services.locks import ReadWriteLock


def test_writer_waits_for_readers_and_blocks_new_readers():
    lock = ReadWriteLock()
    events: list[str] = []
    reader_inside = threading.Event()
    release_reader = threading.Event()

    def first_reader():
        with lock.shared():
            events.append("reader 1 in")
            reader_inside.set()
            release_reader.wait(2)
            events.append("reader 1 out")

    def writer():
        with lock.exclusive():
            events.append("writer")

    def late_reader():
        with lock.shared():
            events.append("reader 2")

    threads = [threading.Thread(target=first_reader)]
    threads[0].start()
    assert reader_inside.wait(2)
    threads.append(threading.Thread(target=writer))
    threads[1].start()
    time.sleep(0.1)  # the writer is now waiting for reader 1
    threads.append(threading.Thread(target=late_reader))
    threads[2].start()
    time.sleep(0.1)  # reader 2 queues behind the waiting writer
    assert events == ["reader 1 in"]

    release_reader.set()
    for thread in threads:
        thread.join(2)
    assert events == ["reader 1 in", "reader 1 out", "writer", "reader 2"]


def test_readers_share_the_lock():
    lock = ReadWriteLock()
    with lock.shared(), lock.shared():
        pass
    with lock.exclusive():
        pass
