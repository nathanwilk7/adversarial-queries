SELECT count(*)
FROM aka_title, cast_info, kind_type, movie_info, movie_link, role_type, title
WHERE kind_type.kind = 'tv series'
  AND aka_title.kind_id = kind_type.id
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.role_id = role_type.id
  AND movie_info.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND title.kind_id = kind_type.id;
