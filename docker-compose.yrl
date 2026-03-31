version: '3.8'
services:
  my_app:
    build: .        # Искать Dockerfile в этой же папке
    restart: always # Вот она, ваша автономность!
