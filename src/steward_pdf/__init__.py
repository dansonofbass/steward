"""Opening statement PDFs (PDF statements spec P8-P14; remote-reading amendment P54-P62): the sandboxed child, its
seccomp filter and Landlock wall, the lines it writes, and the parent's checks of what it prints. The NAS and the
gateway both import it; it imports neither, nor anything but the standard library, steward_boundary and, inside the
child only, the PDF libraries."""
