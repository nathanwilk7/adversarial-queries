SET join_collapse_limit = 1;
SELECT count(*)
FROM ((name CROSS JOIN (cast_info CROSS JOIN (title CROSS JOIN complete_cast))) CROSS JOIN movie_keyword) CROSS JOIN kind_type
WHERE kind_type.kind = 'movie'
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND complete_cast.movie_id = title.id
  AND movie_keyword.movie_id = title.id
  AND title.kind_id = kind_type.id;
