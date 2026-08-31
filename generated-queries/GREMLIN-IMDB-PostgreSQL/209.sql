SELECT count(*)
FROM cast_info, kind_type, movie_info, movie_keyword, movie_link, role_type, title
WHERE kind_type.kind = 'tv series'
  AND cast_info.movie_id = title.id
  AND cast_info.role_id = role_type.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND title.kind_id = kind_type.id;
